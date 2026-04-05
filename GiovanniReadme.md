# IS-MPC – Reactive Step Timing Adaptation

Estensione del workspace IS-MPC originale (Scianca et al.) con un **reactive step adaptation layer** che permette di modificare online tempo e posizione dei passi in risposta a perturbazioni esterne, senza alterare il piano nominale.

---

## Setup (Ubuntu 24.04.3 LTS x86_64)

Conviene creare un venv dedicato:

```bash
# 1. Crea il venv
python3 -m venv ~/venvs/dev

# 2. Attivalo
source ~/venvs/dev/bin/activate

# 3. Vai nella cartella del progetto
cd ~/civale_leonardi_ismpc

# 4. Installa le dipendenze
pip install -r requirements.txt

# 5. Controlla che gli import funzionino
python -c "import dartpy, casadi, scipy, matplotlib, osqp, yaml, numpy; print('ok')"

# 6. Lancia i test (meglio in headless)
python simulation.py --headless
```

**Alias comodo** — da mettere in `~/.zshrc` o `~/.bashrc`:

```bash
alias activate-dev="source ~/venvs/dev/bin/activate"
```

---

## Idea generale

Il workspace originale IS-MPC è un baseline a timing fisso: planner passi nominale, MPC principale, generatore traiettorie piedi swing e inverse dynamics, ma senza un layer reattivo per modificare online tempo e posizione dei passi.

L'estensione aggiunge un modulo **StepTimingAdapter** sopra il baseline con questa logica:

- Il baseline MPC resta il controller principale.
- Quando arriva una perturbazione e il sistema entra in una situazione critica, il modulo può modificare la durata del single support dello step corrente e la posizione del prossimo passo.
- Il piano nominale originale viene preservato intatto.

---

## Modifiche rispetto ai file originali

### `footstep_planner.py`

Il file originale conteneva solo `self.plan` (piano unico costruito offline). Nella versione modificata sono stati introdotti:

- `self.nominal_plan`: piano nominale immutabile.
- `self.plan`: piano attivo modificabile online.
- Funzioni per leggere uno step dal piano nominale o attivo, aggiornare posizione/angolo/`ss_duration` di uno step (`update_step`), calcolare fase e tempo rimanente, convertire coordinate world↔local rispetto al piede di supporto, ottenere il displacement locale del prossimo passo e la durata totale del piano.

Il layer reattivo deve poter modificare online il piano attivo mantenendo disponibile il piano nominale come riferimento.

### `step_timing_adapter.py` *(file nuovo)*

Cuore dell'estensione. Il modulo:

1. Calcola la DCM corrente.
2. Valuta una condizione di attivazione basata su `dcm_error` e *viability margin*.
3. Risolve un piccolo QP con 7 variabili: `dx, dy` (spostamento locale del prossimo passo), `tau` (timing adattato), `bx, by` (offset DCM), `sx, sy` (slack variables).
4. Se la soluzione è valida, converte `tau` in `proposed_ss`, aggiorna `ss_duration` e posizione del prossimo passo nel piano attivo, e salva statistiche (updates, activations, qp_failures, last_update_tick, max_dcm_error).

### `foot_trajectory_generator.py`

Il generatore originale usava cubiche per posizione/orientazione e quartiche per la quota verticale, con durata fissa e target noto. La versione modificata:

- Legge il piano attivo a ogni chiamata.
- Rileva cambiamenti di timing o target di landing.
- Esegue re-anchoring della swing trajectory.
- Usa quintiche con vincoli di posizione/velocità/accelerazione (invece della versione originale più semplice).
- Mantiene il piede sopra il terreno in modo robusto.

Questa modifica è necessaria per rendere coerente l'adattamento sul full humanoid: cambiare online la durata del passo o la landing location senza aggiornare la swing trajectory renderebbe il sistema incoerente.

### `simulation.py`

File con le modifiche più estese. Aggiunte principali:

- Parsing di argomenti CLI (`argparse`).
- Modalità `--headless` per test ripetibili.
- Scheduling dei push da riga di comando.
- Inizializzazione e uso del `StepTimingAdapter`.
- Summary finale dei test, fall detection e possibilità di usare il viewer solo per ispezione qualitativa.
- Tutti i parametri del layer reattivo inseriti in `self.params` dentro `Hrp4Controller`.

Nel loop di controllo: lettura stato → filtro CoM/ZMP con Kalman → `step_timing_adapter.maybe_adapt(...)` → solve MPC principale → generazione traiettorie piedi swing → applicazione torques → push (se schedulato) → aggiornamento log/tempo/fall detection.

### `ismpc.py`

Il cuore dell'MPC non è stato riscritto: continua a risolvere il problema principale con `self.opt.solve()`. Il moving constraint legge `self.footstep_planner.plan` (piano attivo), quindi quando il `StepTimingAdapter` aggiorna tempi e posizioni, l'MPC usa automaticamente il piano adattato. Questo mantiene il baseline quasi intatto e rende il confronto baseline vs adapted molto più pulito.

---

## Pipeline

```
1. Planner nominale         → costruisce il piano passi offline, copiato in un piano attivo
2. State estimation         → recupero stato robot, filtro CoM/ZMP con Kalman
3. Reactive layer           → StepTimingAdapter: se situazione critica, risolve QP e aggiorna piano attivo
4. Main MPC (Ismpc)         → usa il piano attivo per moving constraint e riferimento CoM/ZMP
5. Swing foot generator     → genera traiettoria piede swing coerente col piano aggiornato
6. Inverse dynamics         → produce le coppie articolari finali
7. Perturbazione esterna    → push applicato al robot (se schedulato)
8. Logging / fall detection → statistiche e summary finale
```

---

## Condizioni di attivazione dell'adapter

L'adapter entra **solo** se tutte queste condizioni sono soddisfatte:

- Adaptation abilitata (`use_step_timing_adaptation=True`)
- Siamo in single support (`phase == 'ss'`)
- Non siamo al primo step
- Esiste un passo successivo
- Non siamo nella warmup window iniziale
- Non siamo nella freeze window finale
- Non siamo dentro la cooldown window dopo un update recente

Inoltre deve valere almeno una delle condizioni di attivazione:

- `dcm_error >= adapt_dcm_error_threshold`
- `margin <= -adapt_viability_margin` **e** `dcm_error >= adapt_margin_error_gate`

Se la soluzione del QP è valida e non "troppo piccola", vengono aggiornati timing e/o posizione del prossimo passo.

---

## Parametri del layer reattivo

| Parametro | Descrizione |
|---|---|
| `use_step_timing_adaptation` | Attiva/disattiva il layer |
| `adapt_dcm_error_threshold` | Soglia principale su `dcm_error` |
| `adapt_viability_margin` | Soglia sulla margin |
| `adapt_margin_error_gate` | Soglia minima su `dcm_error` per attivazione via margin |
| `adapt_alpha_step` | Peso del costo su `dx, dy` |
| `adapt_alpha_time` | Peso del costo su `tau` |
| `adapt_alpha_offset` | Peso del costo sull'offset DCM |
| `adapt_alpha_slack` | Penalità sulle slack variables |
| `adapt_debug` | Abilita i log dell'adapter |
| `adapt_debug_every` | Frequenza di logging |
| `adapt_debug_reasons` | Stampa i motivi di skip |
| `T_gap_ticks` | Impedisce timing troppo vicino all'istante corrente |
| `adapt_freeze_ticks` | Blocca l'adapter negli ultimi tick dello step |
| `adapt_warmup_ticks` | Blocca l'adapter all'inizio dello step |
| `adapt_cooldown_ticks` | Tempo minimo tra due update |
| `min_timing_update_ticks` | Update minimo di timing per accettare la soluzione |
| `min_step_update` | Update minimo di posizione per accettare la soluzione |
| `step_length_forward_margin` | Bound geometrico (forward) |
| `step_length_backward_margin` | Bound geometrico (backward) |
| `step_width_outward_margin` | Bound geometrico (outward) |
| `step_width_inward_margin` | Bound geometrico (inward) |
| `cross_margin` | Bound geometrico (cross) |
| `T_min_ticks` / `T_max_ticks` | Bound temporali del QP |

---

## Argomenti CLI

```
--adapt              Attiva il layer reattivo
--headless           Esecuzione senza viewer per test ripetibili
--steps N            Numero massimo di tick in headless
--force F            Intensità del push (N)
--duration D         Durata del push (s)
--push-step S        Step index del planner in cui applicare il push
--push-time T        Tempo assoluto del push
--push-phase P       Frazione del single support per il push start
--direction DIR      left | right | forward | backward
--realtime-factor R  Velocità del viewer
--quiet              Output ridotto
```

Nella batteria finale sono stati usati anche `--profile` (scenario: forward, inplace) e `--log-json` (salva summary JSON di ogni run).

---

## Utilizzo

**Con viewer** (ispezione qualitativa):

```bash
python simulation.py
python simulation.py --adapt
```

**Headless** (test quantitativi):

```bash
# Baseline
python simulation.py --headless --quiet --steps 1400 \
    --force 40 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05

# Con adaptation
python simulation.py --headless --quiet --adapt --steps 1400 \
    --force 40 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55
```

> **Nota:** per i risultati del report la source of truth sono solo i run headless, perché il viewer può chiudersi direttamente se il solver lancia un'eccezione.

---

## Risultati

### Forward walking

| Configurazione | Forza | Esito | Dettagli |
|---|---|---|---|
| Baseline | 30 N | ✅ Completo (1400 tick) | Nessun failure |
| Baseline | 40 N | ❌ Fail a 4.8 s | MPC infeasible (RuntimeError) |
| Adapted | 40 N | ✅ Completo (14.0 s) | 1 update, 1 activation, 0 QP failures |
| Adapted | 50 N | ❌ Fail a 5.0 s | 1 update, 3 activations, 2 QP failures |

Il layer adattivo migliora la robustezza: a 40 N il baseline fallisce mentre la versione adapted completa il run. Il recovery è soprattutto tramite **step placement adaptation**.

### Stepping in place

| Configurazione | Forza | Esito | Dettagli |
|---|---|---|---|
| Baseline | 20 N | ✅ Completo | — |
| Baseline | 30 N | ✅ Completo | — |
| Adapted | 30 N | ✅ Completo (14.0 s) | 3 updates, 3 activations, 0 QP failures |
| Adapted | 40 N | ❌ Fail a 4.79 s | 2 updates, 13 activations, 11 QP failures |

Nello stepping in place si osserva un vero cambio di timing nei log (`ss:70→69` al tick 0520, step 4), che rappresenta una **timing adaptation reale** e non solo foot placement.

---

## Differenze rispetto al paper

- **Architettura**: estensione del workspace IS-MPC del prof, non reimplementazione completa del controller del paper.
- **Traiettoria verticale del piede swing**: il paper usa un QP su polinomio di ordine 9 ricalcolato a ogni ciclo; qui si usano quintiche con re-anchoring online (soluzione più leggera).
- **Whole-body control**: riusata l'inverse dynamics del workspace originale, senza reimplementare la gerarchia completa del paper.
- **Comportamento osservato**: coerente con il paper — nel forward walking il recovery è soprattutto tramite foot placement; nello stepping in place si osserva anche timing adaptation esplicita.

---

## Conclusione

- Rispetto al baseline, è stato aggiunto un reactive layer che modifica online il piano attivo senza toccare il piano nominale.
- Nel forward walking il layer migliora la robustezza (a 40 N il baseline fallisce, la versione adapted regge).
- Nello stepping in place si ha prova esplicita di timing adaptation reale (`ss:70→69`), non solo foot placement.
- Il modulo di step timing adaptation è implementato, funziona sul full humanoid e mostra sia miglioramento di robustezza sia vera modifica del timing.
