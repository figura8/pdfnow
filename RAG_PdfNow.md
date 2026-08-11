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

### reflow_pipeline.py — Config (v27, aggiornata)

```python
# Stile notarile denso (da analisi originale Palatino Linotype 12pt)
BODY_FONT = "Times-Roman"     # Nomi PyMuPDF validi (NON "tiro"/"tibo"/"tiit"!)
BODY_SIZE = 11.0              # pt
LINE_SPACING = 1.02           # interlinea quasi singola
TITLE_SCALE = 1.05            # titoli quasi uguali al corpo
TITLE_FONT = "Times-Bold"
ITALIC_FONT = "Times-Italic"
BOLDITALIC_FONT = "Times-BoldItalic"

# Gerarchia spazi a tre livelli (da style guide originale)
SPACE_TIGHT = 0.5             # corpo→corpo, intra-lista
SPACE_LIGHT = 2.5             # persona→persona, dopo label
SPACE_SECTION = 5.0           # prima di articolo/ruolo/sottotitolo
SPACE_AFTER_HEADING = 2.0     # dopo titoli e label

# Area testo a 300 DPI
TEXT_LEFT_PX = 290, TEXT_RIGHT_PX = 1870
TEXT_TOP_PX = 355, TEXT_BOTTOM_PX = 3420

# Rasterizzazione
RASTER_DPI = 300, BLUR_RADIUS = 0.08, JPEG_QUALITY = 95

# Testi editati (tutte le pagine 1-7)
EDITED_TEXTS = {
    1: "pagina1_v3.txt", 2: "export/pagina2_v3.txt",
    3: "export/pagina3_v3.txt", 4: "export/pagina4_v3.txt",
    5: "export/pagina5_v3.txt", 6: "export/pagina6_v3.txt",
    7: "export/pagina7_ocr.txt",
}
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

### Output finale

| File | Descrizione |
|---|---|
| `export/atto_finale_v12.pdf` | Versione corrente: 4 pagine testo + 2 planimetrie |
| `export/atto_reference_francesco_v5.pdf` | Versione precedente (9 pagine) |
| `export/reflow_pipeline.py` | Script di ripaginazione |
| `export/_render_v1.py` | Script rendering firma |

### Modifiche sostanziali al testo (da originale 3 venditori a 1)

| Modifica | Dettaglio |
|---|---|
| Venditori | 3 (Francesco 2/3, Mariano 1/6, Giovanna 1/6) → 1 (Francesco intera quota) |
| Art.3 GARANZIE E PROVENIENZA | Rimosso. PROVENIENZA spostata in coda Art.1 (solo rogito 1986) |
| Articoli rinumerati | Art.4→3, Art.5→4, Art.6→5, Art.7→6, Art.8→7, Art.9→8, Art.10→9, Art.11→10 |
| PROVENIENZA | Solo atto Lomonaco 1986. Nessun riferimento a successione, decesso, moglie, eredità |
| REGIME PATRIMONIALE | "Vedovo" → "dichiara di alienare bene di natura personale" |
| Prezzo | €75.000 reso esplicito (originale implicito) |
| Conteggio facciate | Aggiornato a 3 fogli, 12 facciate |

### Formattazione (da analisi originale)

| Elemento | Font |
|---|---|
| Corpo testo | Times-Roman 11pt |
| Titoli articoli (Art.1, Art.2...) | Times-Bold 11.55pt, centrato |
| "SONO PRESENTI:" | Times-Bold, allineato a sinistra |
| "quale parte venditrice/acquirente" | Times-BoldItalic, centrato |
| "il tutto censito..." | Times-Italic |
| Nomi parti (ESPOSITO FRANCESCO) | Bold (solo il nome, non l'anagrafica) |
| Numeri catastali | Bold sul numero, regular sull'etichetta |

### Lezioni apprese (reflow)

1. **Font PyMuPDF**: usare `Times-Roman`/`Times-Bold`/`Times-Italic`, NON `tiro`/`tibo`/`tiit` (non riconosciuti → Helvetica)
2. **Desillabazione**: estendere regex a maiuscole (`[A-Za-z]`) per nomi propri (FRAN-CESCO → FRANCESCO)
3. **Classificazione per paragrafo**: il pipeline assegna UNO stile per paragrafo. Separare gli elementi con blank line nei `.txt` è essenziale
4. **Layer ricercabile**: dopo rasterizzazione, il layer invisibile usa `fontname=BODY_FONT`, non hardcodato `helv`
5. **Tre livelli di spazio**: tight (0.5pt corpo→corpo), section (5pt cambio sezione), after-heading (2pt)

### Esito del test corrente

- 6 pagine totali (4 testo + 2 planimetrie);
- ~50-52 righe per pagina (densità notarile);
- `Mariano`, `Giovanna`, `procura`, `vedovo`, `decesso`, `moglie` assenti;
- firme finali: Francesco Esposito, Alessandro Ruggiero e il Notaio;
- PROVENIENZA: solo rogito Lomonaco 1986.

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

## Compositing Firma (Pipeline di Inserimento Firma)

Inserimento della firma di Francesco Esposito in sostituzione di Mariano Esposito
sulla pagina 7 dell'atto.

### Sorgenti

| File | Descrizione |
|---|---|
| `immagine2.png` | Pagina 7 senza la firma di Mariano, 300 DPI |
| `firma3.png` | Campione firma Francesco, 2141×734 px, no DPI |
| `campione_tratto.png` | Zoom dei tratti penna esistenti (riferimento texture/colore) |

### Approccio finale validato: power-curve + texture transfer

Dopo aver testato erosione morfologica, distance-transform thinning, skeletonize
(Zhang-Suen, skimage) a 96 e 300 DPI, l'approccio che funziona è:

1. **Alpha mask** da `firma3.png` via luminanza, upscalata a ~749×257 px (SCALE=0.35)
2. **Power curve** `alpha ** POWER` per assottigliare preservando la forma organica
   (niente skeleton — lo skeleton introduce artefatti e perde dettaglio)
3. **Texture transfer** da `campione_tratto.png`: grana carta e rumore ad alta frequenza
4. **Striature** (rumore anisotropico verticale): simula i solchi della sfera della biro
5. **Vuoti** (probabilistici): micro-salti della punta, densità configurabile
6. **Scanner noise** + **JPEG bake**: rumore di scansione e compressione

### Analisi di `campione_tratto.png`

| Metrica | Valore |
|---|---|
| Colore inchiostro (mediana RGB) | (13, 8, 10) — quasi nero, leggermente caldo |
| Larghezza tratto (FWHM) | ~63 px a risoluzione campione |
| Transizione bordo (10%→90%) | ~4 px — bordi netti |
| Texture σ (su inchiostro) | 14.24 |
| Striature (% pixel con texture lineare) | 89.6% |
| Vuoti (% pixel) | 2.5% |

### Parametri correnti (v22, `_render_v1.py`)

| Parametro | Valore | Ruolo |
|---|---|---|
| `INK_COLOR` | (0, 0, 0) | Colore inchiostro RGB |
| `POWER` | 2.5, 2.8 | Spessore tratto (più alto = più sottile) |
| `VOID_DENSITY` | 7.00 (700%) | Micro-salti punta |
| `STRIATION_STRENGTH` | 5.0 | Intensità solchi sfera |
| `SCANNER_NOISE_SIGMA` | 1.6 | Grana scansione |
| `BLUR` | 0.8 | Morbidezza bordi |
| `SCALE` | 0.35 | Dimensione firma |
| `PLACE_X, PLACE_Y` | 952, 2342 | Posizione sulla pagina |

### Output finale

- **PDF**: `export/atto_finale_con_firma.pdf` — 7 pagine, pagina 7 con firma Francesco
- **Script rendering**: `export/_render_v1.py`
- **Script tuning**: `export/_tune_zs.py` (skeleton), `export/_tune_core.py` (threshold), `export/_tune_skeleton.py`, `export/_tune_dt.py` (distance transform)
- **Script analisi**: `export/_extract_profile.py`, `export/_analyze_stroke.py`, `export/_sample_ink.py`

### Lezioni apprese

1. **Mai skeletonizzare a bassa risoluzione**: lo skeleton a 96 DPI perde dettaglio
   e crea gap. Se serve skeleton, farlo a 300 DPI con `skimage.morphology.skeletonize`.
2. **La power curve sull'alpha originale** preserva la forma organica molto meglio
   di skeleton+dilate, che produce tratti artificialmente uniformi.
3. **Il colore inchiostro va campionato dal tratto puro**, non da zone con testo
   stampato. L'RGB (77,77,77) era il grigio del testo, non l'inchiostro della penna.
4. **Bordi netti**: il campione mostra bordi quasi netti (4 px transizione) —
   usare blur > 0.3 snatura la texture della biro.
5. **I difetti fanno la differenza**: striature, vuoti e rumore di scansione sono
   ciò che distingue una firma vera da una sintetica.

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
