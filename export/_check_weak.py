"""Find remaining weak points in atto_v11_clean."""
import fitz

ours = fitz.open(r"c:\Users\maurizio\Documents\pdfnow\export\atto_v11_clean.pdf")
text = ""
for i in range(6):
    text += ours[i].get_text() + "\n"
ours.close()

issues = [
    ("parti costituite", "Riferimento plurale"),
    ("i costituiti", "Plurale costituiti"),
    ("i comparenti", "Plurale comparenti"),
    ("venditori", "Venditori plurale"),
    ("dichiarano", "Verbo plurale dichiarano"),
    ("convengono", "Verbo plurale convengono"),
    ("SONO PRESENTI", "Intestazione plurale"),
    ("intera quota", "Dicitura intera quota"),
    ("per l intera", "Dicitura per intera"),
    ("85.000,00", "Prezzo 85.000 formato"),
    ("75.000", "Importo 75.000"),
    ("diecimila", "10.000 in lettere"),
    ("ottantacinquemila", "85.000 in lettere"),
    ("assegno circolare", "Assegno circolare"),
    ("non trasferibile", "Assegno non trasferibile"),
    ("quietanza", "Quietanza"),
    ("ipoteca legale", "Ipoteca legale"),
    ("mediazione", "Mediazione"),
    ("mediatore", "Mediatore"),
    ("allegat", "Riferimento allegati"),
    ("planimetr", "Riferimento planimetrie"),
    ("fogli", "Conteggio fogli"),
    ("facciate", "Conteggio facciate"),
    ("prestazione energetica", "APE riferimento"),
    ("scoperto", "Posto auto scoperto"),
    ("vedovo", "Stato civile vedovo"),
    ("coniugato", "Stato civile coniugato"),
    ("separazione", "Separazione beni"),
    ("dieci e trenta", "Orario sottoscrizione"),
    ("Credit Agricole", "Banca Credit Agricole"),
    ("Afragola", "Luogo Afragola"),
    ("Caivano", "Notaio Caivano"),
    ("Amendola", "Via Amendola"),
    ("Riziero Corrado Ruopolo", "Nome Notaio"),
    ("Scisciano", "Nascita Francesco"),
    ("ESPOSITO FRANCESCO", "Nome Francesco"),
    ("RUGGIERO ALESSANDRO", "Nome Ruggiero"),
    ("Repertorio", "Repertorio"),
    ("Raccolta", "Raccolta"),
    ("POSSESSO", "Art. POSSESSO"),
    ("URBANISTICA", "Art. URBANISTICA"),
    ("REGIME PATRIMONIALE", "Art. REGIME PATRIMONIALE"),
    ("PRIVACY", "Art. PRIVACY"),
    ("FISCALI", "Art. FISCALI"),
    ("F.to", "Firme F.to"),
    ("COMUNI-PERTINENZE", "Art. COMUNI-PERTINENZE"),
    ("CONSENSO E OGGETTO", "Art. CONSENSO"),
    ("PREZZO", "Art. PREZZO"),
]

print("PUNTI DEBOLI NEL DOCUMENTO v11")
print("=" * 80)

for term, desc in issues:
    count = text.lower().count(term.lower())
    if count > 0:
        idx = text.lower().find(term.lower())
        ctx = text[max(0,idx-15):idx+len(term)+50].replace('\n',' ').strip()
        print(f"  [{desc}] PRESENTE ({count}x): ...{ctx}...")
    else:
        print(f"  [{desc}] ASSENTE ⚠️")

# Also check for issues that SHOULD be absent but are present
print("\n\nPOTENZIALI INCONGRUENZE")
print("=" * 80)

bad_terms = [
    ("Mariano", "Nome Mariano (dovrebbe essere assente)"),
    ("Giovanna", "Nome Giovanna (dovrebbe essere assente)"),
    ("1/6", "Quota 1/6 (dovrebbe essere assente)"),
    ("2/3", "Quota 2/3 (dovrebbe essere assente)"),
    ("procura", "Procura (dovrebbe essere assente)"),
    ("procuratore", "Procuratore (dovrebbe essere assente)"),
]
for term, desc in bad_terms:
    count = text.lower().count(term.lower())
    if count > 0:
        print(f"  ❌ {desc}: TROVATO ({count}x)")
    else:
        print(f"  ✅ {desc}: assente")
