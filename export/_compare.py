"""Compare original REP 1182 vs our edited atto_v11_clean."""
import fitz

orig = fitz.open(r"C:\Users\maurizio\Downloads\REP 1182.PDF.pdf")
orig_text = ""
for i in range(7):
    orig_text += orig[i].get_text() + "\n"
orig.close()

ours = fitz.open(r"c:\Users\maurizio\Documents\pdfnow\export\atto_v11_clean.pdf")
our_text = ""
for i in range(6):
    our_text += ours[i].get_text() + "\n"
ours.close()

checks = [
    ("Mariano", "Presenza nome Mariano"),
    ("Giovanna", "Presenza nome Giovanna"),
    ("GIANNINI MARIA", "Presenza GIANNINI MARIA"),
    ("2/3", "Quota 2/3"),
    ("1/6", "Quota 1/6"),
    ("procura", "Riferimento procura"),
    ("procuratore", "Riferimento procuratore"),
    ("Lomonaco", "Rogito Lomonaco (provenienza)"),
    ("12830", "Rep. 12830/7605"),
    ("144013", "N. trascrizione 144013"),
    ("GARANZIE", "Sezione GARANZIE"),
    ("PROVENIENZA:", "Sezione PROVENIENZA"),
    ("successione", "Riferimento successione"),
    ("accettazione tacita", "Accettazione tacita eredita"),
    ("Art.3)", "Art.3) (GARANZIE in orig)"),
    ("Art.4)", "Art.4) (PREZZO in orig)"),
    ("Art.11)", "Art.11) (FISCALI in orig)"),
    ("Art.10)", "Art.10) (PRIVACY in orig)"),
    ("75.000", "Importo 75.000 esplicito"),
    ("4 (quattro) fogli", "Conteggio fogli/facciate"),
    ("Credit Agricole", "Banca Credit Agricole"),
    ("F.to ESPOSITO FRANCESCO", "Firma Francesco"),
    ("F.to RUGGIERO", "Firma Ruggiero"),
    ("F.to RIZIERO", "Firma Notaio"),
    ("SONO PRESENTI:", "Intestazione SONO PRESENTI"),
    ("quale parte venditrice", "Qualifica venditrice"),
    ("quale parte acquirente", "Qualifica acquirente"),
    ("Allegato", "Riferimento allegati"),
    ("lettera", "Riferimento lettere allegati"),
    ("prima casa", "Agevolazioni prima casa"),
    ("9%", "Tassazione 9% F/1"),
    ("Euro 300,00", "Prezzo F/1 Euro 300"),
    ("Euro 85.000", "Prezzo totale 85.000"),
    ("mq. 60", "Superficie F/1 60 mq"),
    ("mq. 83", "Superficie F/1 83 mq"),
    ("mq. 16", "Superficie C/7 16 mq"),
    ("Foglio 61", "Foglio 61"),
    ("Mappale 506", "Mappale 506"),
    ("Sub. 1", "Subalterno 1 (abitazione)"),
    ("Sub. 6", "Subalterno 6 (F/1)"),
    ("Sub. 11", "Subalterno 11 (F/1)"),
    ("Sub. 19", "Subalterno 19 (C/7)"),
    ("cat. A/3", "Categoria A/3"),
    ("cat. F/1", "Categoria F/1"),
    ("cat. C/7", "Categoria C/7"),
    ("RUGGIERO ALESSANDRO", "Acquirente Ruggiero"),
    ("ESPOSITO FRANCESCO", "Venditore Francesco"),
    ("Praia a Mare", "Comune Praia a Mare"),
    ("Contrada Foresta", "Contrada Foresta"),
    ("Repertorio n. 1182", "Repertorio 1182"),
    ("Raccolta n. 912", "Raccolta 912"),
    ("1490", "Art. 1490 c.c. (garanzie vizi)"),
    ("1491", "Art. 1491 c.c. (esclusione vizi)"),
    ("2648", "Art. 2648 c.c. (accettazione)"),
    ("D.P.R. 131/1986", "D.P.R. 131/1986"),
    ("D.lgs. 192/2005", "D.lgs. 192/2005 (APE)"),
]

print(f"{'ELEMENTO':<38} | {'ORIG':>4} | {'NOSTRO':>6} | NOTE")
print("-" * 100)
for term, desc in checks:
    in_orig = term.lower() in orig_text.lower()
    in_ours = term.lower() in our_text.lower()
    if in_orig and in_ours:
        status = "✓ coerente"
    elif in_orig and not in_ours:
        status = "✗ RIMOSSO"
    elif not in_orig and in_ours:
        status = "+ AGGIUNTO"
    else:
        status = "- assente"
    print(f"{desc:<38} | {'SI' if in_orig else 'NO':>4} | {'SI' if in_ours else 'NO':>6} | {status}")

# Summary stats
removed = sum(1 for t, _ in checks if t.lower() in orig_text.lower() and t.lower() not in our_text.lower())
kept = sum(1 for t, _ in checks if t.lower() in orig_text.lower() and t.lower() in our_text.lower())
print(f"\nRiepilogo: {kept} elementi conservati, {removed} rimossi")
