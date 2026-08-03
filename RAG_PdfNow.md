# PdfNow — Riepilogo Tecnico Completo

## Obiettivo del Progetto

Tool per lavorare con PDF scansionati: OCR, correzione testo, ricostruzione mantenendo lo stile grafico. Local-first, Python backend, CLI.

---

## Architettura Attuale

```
pdfnow/
├── pdfnow/
│   ├── model.py      # Document Model: Document → Page → Block → Line → Word + BBox
│   ├── ocr.py        # OCR via Tesseract + pre-processing OpenCV (denoise, CLAHE, Otsu)
│   ├── export.py     # Export PDF ricercabile (layer immagine + testo invisibile)
│   ├── style.py      # Estrazione stile (font, margini, layout) + analyze_layout()
│   └── cli.py        # CLI in 5 comandi: ocr, edit, export, text, rebuild
├── export/           # Output directory
└── test_project.json # Progetto di test (atto notarile, 1 pagina, 411 parole OCR)
```

---

## Document Model (model.py)

```python
Document
  └── Page
        ├── image_path    # PNG della pagina a 300 DPI
        ├── width, height # dimensioni in pixel
        └── Block[]
              ├── bbox: BBox (x0,y0,x1,y1 in pixel a 300 DPI)
              ├── lines: Line[]
              │     └── words: Word[]
              │           ├── text, bbox, confidence (0-1)
              │           ├── corrected_text | None
              │           └── status: untouched/corrected/confirmed/locked
              ├── block_type: text/image/table/stamp/signature
              ├── label: str  # "body", "sidebar", "header", "footer" (da analyze_layout)
              ├── replacement_text: str | None
              └── deleted: bool
```

---

## Comandi CLI

### 1. OCR
```bash
pdfnow ocr scanned.pdf -l ita -p 1           # -p = max pagine
# Output: export/scanned.pdfnow.json
```
- Renderizza pagina a 300 DPI con PyMuPDF
- Pre-processing: denoising, CLAHE, Otsu binarization (OpenCV)
- Tesseract con --psm 3, output word-level con bbox e confidence
- Salva immagine pagina in `.pdfnow/` e metadati nel JSON

### 2. Correzione parole (edit)
```bash
pdfnow edit progetto.json -c corrections.json
# corrections.json: {"parola_errata": "parola_corretta", ...}
```

### 3. Editing strutturale blocchi (block-edit)
```bash
pdfnow blocks progetto.json                              # elenca blocchi
pdfnow block-edit progetto.json -f block_edits.json       # applica modifiche
# block_edits.json: {"edits": [{"page":1, "block":0, "replacement_text":"..."}]}
```

### 4. Estrai testo strutturato (text)
```bash
pdfnow text progetto.json -p 1 -o da_modificare.txt
```
- Preserva a capo e paragrafi (rilevati da gap > 2.5x altezza mediana)
- Stampa metriche stile auto-rilevate

### 5. Esporta PDF ricercabile (export)
```bash
pdfnow export progetto.json --preview -o preview.pdf     # overlay visibile
pdfnow export progetto.json -o searchable.pdf             # testo invisibile
```
- **FIX:** usa `insert_text()` su baseline, non `insert_textbox()` (41 fallimenti silenziosi risolti)
- Restituisce `(Path, list[str])` con warning di overflow
- Preview: testo visibile colorato per confidence (verde/giallo/rosso)
- Block replacement: wrapping con metriche font reali, auto-fontsize

### 6. Ricostruisci da testo editato (rebuild)
```bash
pdfnow rebuild progetto.json -t testo_modificato.txt \
  --font-size 10 --font-name tiro --align left \
  --keep-sidebar --para-gap 4 \
  -o export/ricostruito.pdf
```
- **FIX:** ora renderizza riga per riga con `wrap_text_to_lines()` + `insert_text()`
- Abortisce con `ClickException` se overflow (nessun PDF parziale)
- `--keep-sidebar`: white-out aggressivo a sinistra della sidebar
- `--font-name`: tiro (Times Roman), helv, cour
- Grassetti automatici su pattern noti (COMPRAVENDITA, REPUBBLICA ITALIANA, etc.)

---

## Test Case: Atto Notarile (13 pagine)

**File originale:** `REP 1182.PDF.pdf` — 30 pagine totali, test su prime 13.

**Modifica:** 3 venditori → 1 (Francesco Esposito). Rimosso Mariano, Giovanna, procura.

### Workflow

1. **OCR** 13 pagine → `export/atto_13p.json` (3592 parole, 94.6% conf)
2. **Identificate** le pagine dell'atto da modificare e il blocco procura 8-11
3. **P8-11 escluse integralmente** (procura Giovanna→Mariano)
4. **P1,3,5,7 editate** via `.txt`:
   - P1: `pagina1_v2.txt` — Francesco unico, "per l'intera quota, vende"
   - P3: `export/pagina3_ocr.txt` — "ESPOSITO FRANCESCO, per l'intera quota"
   - P5: `export/pagina5_ocr.txt` — rimosse righe Mariano e Giovanna
   - P7: `export/pagina7_ocr.txt` — rimossa firma Mariano
5. **Ripaginazione** via `export/reflow_pipeline.py`: flusso unico p1-7 + raster + searchable + planimetrie reference p12-13

### reflow_pipeline.py — Config
```python
BODY_SIZE = 11.7          # pt, reference prevalente 12 pt
LINE_SPACING = 1.35
PARA_SPACING = 2.0
BALANCE_RESERVE_PT = 180.0
TITLE_SCALE = 1.15
TEXT_LEFT_PX = 320, TEXT_RIGHT_PX = 1866
TEXT_TOP_PX = 384, TEXT_BOTTOM_PX = 3403
EDITED_TEXTS = {1: "pagina1_v2.txt", 3: "export/pagina3_ocr.txt",
                5: "export/pagina5_ocr.txt", 7: "export/pagina7_ocr.txt"}
```

### Bug `line_height` risolto in `ripaginate()`
```python
# ERRATO:
line_y = y + (j + 1) * fontsize    # gap zero → parole sovrapposte
# CORRETTO:
line_y = y + line_height
```

Il rendering attuale è riga per riga; il controllo di overflow avviene prima di
ogni inserimento. Non usare nuovamente la formula basata sul solo `fontsize`.

### Struttura verificata delle pagine 1-13

| Pagine reference | Contenuto | Decisione per Francesco unico venditore |
|---|---|---|
| 1-7 | Atto principale | Ricostruire come flusso unico |
| 8-11 | Procura speciale di Giovanna a Mariano | Escludere integralmente: è un unico blocco incompatibile |
| 12-13 | Planimetrie catastali | Conservare direttamente dalla reference |

Non va eliminata soltanto pagina 8: le pagine 9-11 sono la continuazione della
stessa procura e, se mantenute, lasciano frammenti privi di contesto e riferimenti
contraddittori.

---

## Layout Auto-Rilevato (analyze_layout in style.py)

Basato sui blocchi OCR della pagina 1 (2481×3508 px a 300 DPI):

| Blocco | Posizione | Contenuto | Classificazione |
|---|---|---|---|
| 0 | x=320-1866, y=384-3337 | Testo principale | **body** (colonna testo) |
| 1 | x=1085-1101, y=3413-3439 | "1" (numero pagina) | **footer** (>94% altezza) |
| 2 | x=1945-2395, y=314-397 | "Riziero Corrado Ruopolo Notaio" | **sidebar** (x > 70% larghezza) |
| 3-7 | x=1945-2307, y=649-1955 | Timbri registrazione/trascrizione | **sidebar** |

**Area testo pulita (white-out):** x=315-1870, y=379-3408 (gap 75px prima della sidebar)

---

## Stile Auto-Rilevato (extract_style in style.py)

- **Font size body:** 9.4pt (P25 altezze parole × 72/300 × 1.15)
- **Font:** Times Roman (tiro)
- **Line spacing:** 1.70× (da gap medi tra linee OCR)
- **Allineamento:** left (varianza margini sinistri < 2%)
- **Margini:** L=77pt, R=21pt, T=75pt, B=17pt (da bounding box parole)
- **Header:** 1.2× body, grassetto (tibo = Times Bold)

---

## Problemi Noti / Limitazioni

### 1. Rilevamento grassetti
- **Stato attuale:** match esatto su pattern predefiniti (COMPRAVENDITA, REPUBBLICA ITALIANA, SONO PRESENTI:, quale parte venditrice, etc.)
- **Limite:** se l'utente modifica il testo cambiando queste frasi, il grassetto sparisce
- **Soluzione proposta:** supporto Markdown `**testo**` nel file .txt per controllo manuale

### 2. Dimensione font
- **Stato attuale:** auto-rilevata 9.4pt o manuale via --font-size
- **Limite:** l'auto-rilevamento è approssimativo (basato su bounding box Tesseract che includono padding)
- **Test in corso:** confronto tra 9.4pt (auto) e 10pt (manuale)

### 3. Linee di layout strutturali
- **Rimosse** nell'ultima versione perché l'utente non era soddisfatto
- L'OCR non rileva linee grafiche — servirebbe indicazione manuale o analisi dell'immagine con edge detection (OpenCV Canny + HoughLines)

### 4. Blocchi Tesseract troppo grossi
- Tesseract ha raggruppato quasi tutto il testo in un unico blocco (blocco 0)
- Questo rende difficile l'editing selettivo di sezioni specifiche
- Serve un post-processing per dividere i blocchi in paragrafi/sottosezioni

### 5. Ordine di lettura sidebar
- Tesseract mescola le note laterali (timbri) con il flusso del testo principale
- L'estrazione testo (`pdfnow text`) produce output con elementi sidebar interleaved
- `analyze_layout` ora separa correttamente body/sidebar/footer ma il danno è fatto in fase OCR

### 6. Ricostruzione vs overlay
- L'approccio overlay (export) mantiene l'immagine originale ma il testo va solo in overlay invisibile
- L'approccio rebuild (ricostruzione) genera PDF pulito ma:
  - Perde elementi grafici non testuali (stemma, linee, timbri) a meno di --keep-sidebar
  - Il white-out dell'area testo è un rettangolo — non gestisce aree non rettangolari
  - La qualità dell'immagine di sfondo dipende dalla risoluzione della scansione (300 DPI)

### 7. `insert_textbox()` può fallire silenziosamente

- PyMuPDF restituisce un valore negativo quando il rettangolo non contiene il testo.
- Se il valore di ritorno viene ignorato, il layer ricercabile può risultare vuoto.
- Per il layer invisibile validato si usa `insert_text()` riga per riga sulla baseline.
- Se si usa `insert_textbox()`, controllare sempre il ritorno e trattare l'overflow
  come errore, mai come warning ignorabile.

### 8. Titoli inglobati nel corpo

Dopo la fusione delle righe OCR, intestazioni come `PROVENIENZA:`, `GARANZIE:` e
`Art.7)`-`Art.10)` potevano restare unite alla prima frase. La classificazione
applicava così grassetto e centratura a tutto il paragrafo. La pipeline separa ora
esplicitamente le intestazioni note prima di assegnare lo stile.

---

## Pipeline di Reflow Validata (pagine 1-7)

Script: `export/reflow_pipeline.py`

Principio fondamentale: quando una modifica cambia la quantità di testo, le pagine
non devono essere corrette singolarmente. Il corpo delle pagine 1-7 viene estratto,
normalizzato e ripaginato come un unico flusso continuo.

### Parametri validati sulla reference

| Parametro | Valore |
|---|---:|
| Font corpo | Times Roman (`tiro`) |
| Dimensione corpo | 11.7 pt |
| Dimensione prevalente reference | 12 pt |
| Interlinea | 1.35× |
| Spazio dopo paragrafo | 2 pt |
| Margine sinistro | circa 76.8 pt |
| Limite destro corpo | circa 447.8 pt |
| Riserva di bilanciamento pagine 1-6 | 180 pt |
| Rasterizzazione | 300 DPI, JPEG 92 |
| Uniformazione | Gaussian blur 0.25 |

I margini misurati nella reference sono circa 76.6-448 pt: la geometria della
pipeline coincide quindi quasi esattamente con l'originale.

### Regole di impaginazione

1. Desillabare soltanto `parola-\ncontinuazione` quando la continuazione inizia
   con una minuscola; non unire indiscriminatamente righe o paragrafi.
2. Normalizzare virgolette, trattini e legature Unicode prima del rendering.
3. Separare titolo e corpo prima della classificazione tipografica.
4. Calcolare sempre la baseline con l'altezza di riga reale:

   ```python
   line_height = fontsize * LINE_SPACING
   line_y = y + line_height
   ```

5. Eseguire il controllo di overflow riga per riga. Un paragrafo può continuare
   nella pagina successiva; nessun testo deve essere troncato silenziosamente.
6. Applicare `keep_with_next` ai titoli, conservando almeno una riga del corpo.
7. Preservare stemma e timbri reali soltanto sulla pagina 1. Sulle pagine 2-7
   cancellare completamente il vecchio corpo: falsi blocchi sidebar causavano
   duplicazioni e sovrapposizioni.
8. Ricreare uniformemente numeri pagina e layer invisibile ricercabile.

### Verifiche obbligatorie

- numero pagine atteso;
- nessuna pagina vuota;
- almeno 5 parole ricercabili per pagina;
- assenza testuale di `Mariano` e `Giovanna`;
- assenza di `procura` e `procuratore` nell'atto ricostruito;
- pagina 7 compresa tra 15 e 20 righe (attualmente 16);
- tutte le righe del flusso renderizzate;
- controllo visivo mediante contact sheet, perché conteggi e bounding box non
  rilevano da soli grassetti errati o incoerenze percettive.

### Output di riferimento aggiornati

| File | Descrizione |
|---|---|
| `export/atto_finale_v4.pdf` | Test precedente: 7 pagine ricostruite + reference 11-13 |
| `export/atto_reference_francesco_v5.pdf` | Test consigliato: 7 pagine ricostruite + planimetrie reference 12-13 |
| `export/audit_reference_francesco_v5.png` | Anteprima visiva completa del test v5 |

Il file v5 contiene 9 pagine. Le pagine 8-11 della reference sono escluse come
blocco unico. Le planimetrie 12-13 sono incorporate direttamente dal PDF originale
e ricevono un layer OCR invisibile.

### Esito del test v5

- 9 pagine totali;
- pagina 7: 16 righe, 166 parole;
- 214 righe ricostruite;
- testo ricercabile su tutte le pagine;
- `Mariano`, `Giovanna`, `procura` e `procuratore` assenti;
- firme finali: Francesco Esposito, Alessandro Ruggiero e il Notaio;
- nessuna sovrapposizione visiva rilevata nella contact sheet.

---

## Stack Tecnologico

| Componente | Tecnologia |
|---|---|
| OCR | Tesseract 5.4 via pytesseract 0.3.13 |
| PDF read/write | PyMuPDF (fitz) 1.28.0 |
| Image processing | OpenCV 5.0, Pillow 12.3 |
| Numeric | NumPy 2.5 |
| CLI | Click 8.4, Rich 15.0 |
| Python | 3.13.2 |

---

## Prossimi Passi Discussi

1. Integrare la pipeline di reflow validata nei comandi principali, evitando che
   resti uno script sperimentale separato.
2. Rendere configurabile la selezione delle pagine da conservare/escludere e
   registrare nel progetto la motivazione dell'esclusione.
3. Aggiungere test automatici per overflow, layer ricercabile, titoli inline,
   paginazione e parole vietate.
4. Supportare markup esplicito per grassetto, corsivo, centratura e titoli nel
   testo editabile, riducendo la dipendenza da pattern hard-coded.
5. Migliorare la segmentazione OCR di corpo, timbri, firme, sidebar e allegati.
6. Aggiungere un confronto visivo automatico con la reference (margini, densità,
   dimensioni font e anomalie di sovrapposizione).
7. Eventuale UI React + PDF.js per editing visuale (fase 2).
