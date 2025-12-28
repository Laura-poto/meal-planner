# engine.py
# Version robuste: logique issue du notebook, mais organisée en fonctions (sans exécution à l'import).
from __future__ import annotations

import json, math, re, unicodedata
from pathlib import Path
from collections import defaultdict

# ---------- PARAMÈTRES ----------
MATCH_MIN = 100  # filtre des recettes selon score marché (%)
MATCH_MIN_PANTRY = 0   # % minimum côté placard (ex. 100 pour ne garder que 100%)
PANTRY_RAYONS = {"boucherie", "poissonnerie", "épicerie"}  # rayons à scorer côté placard
CATEGORY_ORDER = [
    "craquage","pâtes végé","végé","poulet","boeuf haché","boeuf",
    "porc","canard","saumon","poisson blanc","crevettes","tarte","soupe",
]
FLOAT_EPS = 1e-9  # tolérance flottants


# ---------- NORMALISATION / ALIASES ----------
ALIASES = {
    "Emmental râpé": "Emmental",
    "Dés de butternut": "Butternut",
    "Fricassée de champignons émincés": "Champignon",
    "Gingembre frais": "Gingembre",
    "Oignon jaune": "Oignon",
    "Poivron rouge": "Poivron",
    "Poivrons grillés": "Poivron",
    "Pommes de terre Franceline": "Pommes de terre",
    "Pommes de terre à chair farineuse": "Pommes de terre",
    "Pommes de terre à chair ferme": "Pommes de terre",
    "Purée de gingembre": "Gingembre",
    "Tomates cerises rouges": "Tomates cerises",
    "Tomates cerises rouges et jaunes": "Tomates cerises",
    "Mélange de jeunes pousses": "Salade",
    "Mélange de salades": "Salade",
    "Chou rouge découpé": "Chou rouge",
    "Champignons blonds": "Champignons",
    "Champignons de Paris": "Champignons",
    "Gousse d'ail": "Ail"
}

def normalize(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    words = s.split()
    singularized = []
    for w in words:
        if len(w) > 3 and re.search(r"[sx]$", w):
            w = re.sub(r"[sx]$", "", w)
        singularized.append(w)
    return " ".join(singularized)

ALIASES_NORM = {normalize(k): v for k, v in ALIASES.items()}
def canon(name: str) -> str:
    return ALIASES_NORM.get(normalize(name), name)


# --- Globals initialisés par init(data_dir) ---
DATA_DIR: Path | None = None
recettes = []
catalogue = []
raw_dispos = set()
provisions_path: Path | None = None
provisions = []

CATALOGUE_NORM_TO_PRETTY = {}
rayons_map = {}
indispensables_map = {}
poids_map = {}
REPLACEMENTS_NORM = {}
dispo_norm_to_pretty = {}
dispos_norm = set()
provisions_index = {}
catalogue_norm_index = {}
market_indispensables_norm = set()

def init(data_dir: str | Path):
    """Charge les fichiers data/ et construit les index, exactement comme le notebook."""
    global DATA_DIR, recettes, catalogue, raw_dispos, provisions_path, provisions
    global CATALOGUE_NORM_TO_PRETTY, rayons_map, indispensables_map, poids_map, REPLACEMENTS_NORM
    global dispo_norm_to_pretty, dispos_norm, provisions_index, catalogue_norm_index, market_indispensables_norm

    DATA_DIR = Path(data_dir)
    recettes = json.load(open(str(DATA_DIR / "recettes_hellofresh.txt"), encoding="utf-8"))
    catalogue = json.load(open(str(DATA_DIR / "ingredients_infos.txt"), encoding="utf-8"))
    raw_dispos = set(json.load(open(str(DATA_DIR / "ingredients_disponibles.txt"), encoding="utf-8")))

    provisions_path = DATA_DIR / "provisions.txt"
    provisions = json.load(open(provisions_path, encoding="utf-8")) if provisions_path.exists() else []

    # ---------- INDEX ----------
    # catalogue
    CATALOGUE_NORM_TO_PRETTY = {normalize(canon(i["name"])): canon(i["name"]) for i in catalogue}
    rayons_map = {normalize(canon(i["name"])): i.get("rayon", "").lower() for i in catalogue}
    indispensables_map = {normalize(canon(i["name"])): bool(i.get("indispensable")) for i in catalogue}
    poids_map = {normalize(canon(i["name"])): i.get("poids") for i in catalogue}
    
    # remplacements (tous rayons)
    REPLACEMENTS_NORM = {}
    for item in catalogue:
        base = normalize(canon(item["name"]))
        repls = {normalize(canon(r)) for r in item.get("remplacement", [])}
        REPLACEMENTS_NORM[base] = repls | {base}
    
    # ingrédients_disponibles → pretty & norm
    dispo_norm_to_pretty = {}
    for d in raw_dispos:
        pretty = canon(d)
        dispo_norm_to_pretty.setdefault(normalize(pretty), pretty)
    dispos_norm = set(dispo_norm_to_pretty.keys())
    
    # provisions
    provisions_index = {normalize(canon(p["name"])): p for p in provisions}
    
    # indispensables marché
    catalogue_norm_index = {normalize(canon(i["name"])): i for i in catalogue}
    market_indispensables_norm = {
        normalize(canon(i["name"]))
        for i in catalogue
        if i.get("indispensable") and i.get("rayon", "").lower() == "marché"
    }

# ---------- HELPERS ----------
def pretty_from_norm(n: str) -> str:
    return CATALOGUE_NORM_TO_PRETTY.get(n, dispo_norm_to_pretty.get(n, n))

def find_available_market(norm_name: str):
    for cand in [norm_name] + [c for c in REPLACEMENTS_NORM.get(norm_name, {norm_name}) if c != norm_name]:
        if cand in dispos_norm:
            return cand
    return None

def find_available_pantry(norm_name: str):
    cand_list = [norm_name] + [c for c in REPLACEMENTS_NORM.get(norm_name, {norm_name}) if c != norm_name]
    for cand in cand_list:
        if cand in provisions_index:
            return cand
    return None

# ---------- SCORING RECETTES ----------
def score_recette(r):
    rec_ing_pretty = {canon(n) for n in r["ingredients"].keys()}
    rec_ing_norm = {normalize(n) for n in rec_ing_pretty}
    inconnus = sorted(n for n in rec_ing_pretty if normalize(n) not in catalogue_norm_index)

    # marché
    besoins_m = market_indispensables_norm & rec_ing_norm
    ok_m, manque_m = [], []
    if besoins_m:
        for n_norm in besoins_m:
            base_pretty = pretty_from_norm(n_norm)
            cand = find_available_market(n_norm)
            if cand is None:
                manque_m.append(base_pretty)
            else:
                if cand != n_norm:
                    ok_m.append(f"{base_pretty} (remplacé par : {pretty_from_norm(cand)})")
                else:
                    ok_m.append(base_pretty)
        score_m = 100 * len(ok_m) / len(besoins_m)
    else:
        score_m = 100.0

    # placard (rayons choisis)
    besoins_p = {n for n in rec_ing_norm if rayons_map.get(n) in PANTRY_RAYONS}
    ok_p, manque_p = [], []
    if besoins_p:
        for n_norm in besoins_p:
            base_pretty = pretty_from_norm(n_norm)
            cand = find_available_pantry(n_norm)
            if cand is None:
                manque_p.append(base_pretty)
            else:
                if cand != n_norm:
                    ok_p.append(f"{base_pretty} (remplacé par : {pretty_from_norm(cand)})")
                else:
                    ok_p.append(base_pretty)
        score_p = 100 * len(ok_p) / len(besoins_p)
    else:
        score_p = 100.0

    return {
        "name": r["name"],
        "link": r["link"],
        "category": r.get("category", "non classé"),
        "score_market": round(score_m, 1),
        "score_pantry": round(score_p, 1),
        "ok_market": sorted(ok_m),
        "manque_market": sorted(manque_m),
        "ok_pantry": sorted(ok_p),
        "manque_pantry": sorted(manque_p),
        "inconnus": inconnus,
    }

def compute_matching(data_dir: str | Path, match_min: float = None, match_min_pantry: float = None, write_ingredients_a_completer: bool = False):
    """Calcule les scores et renvoie les mêmes infos que l'affichage du notebook."""
    init(data_dir)
    if match_min is None:
        match_min = MATCH_MIN
    if match_min_pantry is None:
        match_min_pantry = MATCH_MIN_PANTRY

    scored, unknown_global_pretty, seen = [], set(), set()
    for r in recettes:
        key = r["name"]
        if key in seen:
            continue
        seen.add(key)
        s = score_recette(r)
        scored.append(s)
        unknown_global_pretty.update(s["inconnus"])

    scored_all = list(scored)
    scored = [r for r in scored if r["score_market"] >= match_min and r["score_pantry"] >= match_min_pantry]

    def sort_key_recette(r):
        cat = r.get("category", "").lower()
        cat_index = CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)
        return (cat_index, -r["score_pantry"], r["name"].lower())
    scored.sort(key=sort_key_recette)

    # rendu texte comme le notebook
    out_lines = []
    current_cat = None
    for r in scored:
        cat = r.get("category", "non classé")
        if cat != current_cat:
            out_lines.append(f"\n=== {cat.upper()} ===\n")
            current_cat = cat
        out_lines.append(f"{r['score_market']}% marché & {r['score_pantry']}% placard - {r['name']} ({r['link']})")
        out_lines.append("   OK marché : " + (", ".join(r["ok_market"]) if r["ok_market"] else "Aucun"))
        out_lines.append("   Manque marché : " + (", ".join(r["manque_market"]) if r["manque_market"] else "Aucun"))
        out_lines.append("   OK placard : " + (", ".join(r["ok_pantry"]) if r["ok_pantry"] else "Aucun"))
        out_lines.append("   Manque placard : " + (", ".join(r["manque_pantry"]) if r["manque_pantry"] else "Aucun"))
        if r["inconnus"]:
            out_lines.append("[⚠️] Ingrédients non définis dans ingredients_infos.txt : " + ", ".join(r["inconnus"]))
        out_lines.append("")
    text = "\n".join(out_lines)

    unknown_missing = sorted(n for n in unknown_global_pretty if normalize(n) not in catalogue_norm_index)
    if write_ingredients_a_completer and unknown_missing:
        TEMPLATE_MONTHS = ["janvier","février","mars","avril","mai","jui...n","juillet","août","septembre","octobre","novembre","décembre"]
        def render_ing_block(name: str) -> str:
            return (
                "  {\n"
                f"    \"name\": \"{name}\",\n"
                f"    \"saison\": {json.dumps(TEMPLATE_MONTHS, ensure_ascii=False)},\n"
                f"    \"rayon\": \"à définir\",\n"
                f"    \"indispensable\": true\n"
                "  }"
            )
        out_path = DATA_DIR / "ingredients_a_completer.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            blocks = [render_ing_block(n) for n in unknown_missing]
            f.write(",\n".join(blocks))

    return {
        'scored': scored,
        'scored_all': scored_all,
        'text': text,
        'unknown_ingredients': unknown_missing,
    }

# =========================
#   PARTIE 2 — COURSES & PLACARD
# =========================

def scale_and_round(value, unit, factor):
    scaled = value * factor
    if unit and unit.lower().startswith("g"):
        return int(math.ceil(scaled / 10.0) * 10), unit
    return int(math.ceil(scaled)), unit

def _courses_nb(selection_names, personnes):
    """Construit la liste de courses brute (avant déduction du placard), en marquant la dispo marché."""
    factor = personnes / 2
    result = defaultdict(dict)  # rayon -> {ing_norm -> bucket}

    selected, seen = set(selection_names), set()
    for r in recettes:
        if r["name"] not in selected or r["name"] in seen:
            continue
        seen.add(r["name"])

        for ing_raw, data in r["ingredients"].items():
            pretty = canon(ing_raw)
            n = normalize(pretty)
            rayon = rayons_map.get(n, "inconnu")
            if rayon == "placard":
                continue

            # quantités
            if isinstance(data, dict):
                qty = data.get("qty")
                unit = data.get("unit", "")
                override_indisp = data.get("indispensable", None)
            else:
                qty, unit, override_indisp = None, str(data), None

            indisp_flag = override_indisp if override_indisp is not None else indispensables_map.get(n, False)

            val = None
            if isinstance(qty, (int, float)):
                val, unit = scale_and_round(qty, unit, factor)

            # conversions marché (pièces -> kg / g -> kg)
            if (
                rayon == "marché"
                and isinstance(val, (int, float))
                and unit and unit.strip().lower() in ["pièce","pièces","pièce(s)","piece","pieces","piece(s)"]
                and poids_map.get(n)
            ):
                val = round(val * poids_map[n], 2)
                unit = "kg"
            elif rayon == "marché" and unit and unit.lower().startswith("g") and isinstance(val, (int, float)):
                val = round(val / 1000, 2)
                unit = "kg"

            # dispo marché ?
            is_market = (rayon == "marché")
            market_available = (find_available_market(n) is not None) if is_market else None

            bucket = result[rayon].get(n)
            if not bucket:
                bucket = {
                    "label": pretty, "val": 0, "unit": unit, "indispensable": indisp_flag,
                    "recipes": set(), "norm": n, "market_available": market_available
                }
                result[rayon][n] = bucket

            # cumuls
            bucket["indispensable"] = bucket["indispensable"] or indisp_flag
            if val is None:
                bucket["val"] = None
            elif bucket["val"] is not None:
                bucket["val"] += val
            else:
                bucket["val"] = val
            if not bucket["unit"] and unit:
                bucket["unit"] = unit
            if is_market:
                prev = bucket.get("market_available")
                bucket["market_available"] = bool(prev) or bool(market_available)
            bucket["recipes"].add(r["name"])

    # structure d'affichage
    printable = {}
    for rayon, by_norm in result.items():
        printable[rayon] = {}
        for ing_norm, data in by_norm.items():
            data["recipes"] = sorted(data["recipes"])
            printable[rayon][data["label"]] = {
                "val": data["val"],
                "unit": data["unit"],
                "indispensable": data["indispensable"],
                "recipes": data["recipes"],
                "norm": ing_norm,
                "market_available": data.get("market_available"),
            }
    return printable

# -------- Exemple d’utilisation --------

def compute_courses(data_dir: str | Path, selection_names, personnes: int, update_provisions: bool = False):
    """Calcule la liste de courses + déduction placard (comme le notebook)."""
    init(data_dir)
    liste_courses = _courses_nb(selection_names, personnes)
    # ----- AJUSTEMENT SELON LE PLACARD (bloc notebook) -----
    consommation_totale = defaultdict(float)  # quantités réellement prélevées du placard (clé = norm placard/base/remplaçant)
    pantry_used = {}  # pour affichage "PLACARD UTILISÉ"
    
    for rayon, items in liste_courses.items():
        for label, data in list(items.items()):
            base_norm = data["norm"]
            val = data["val"]
            if val is None:
                continue
    
            # recherche robuste dans le placard: base -> (label) -> remplacements
            prov = provisions_index.get(base_norm)
            used_key = base_norm
            if not prov:
                label_norm = normalize(canon(label))
                if label_norm in provisions_index:
                    prov = provisions_index[label_norm]
                    used_key = label_norm
            if not prov:
                for repl in REPLACEMENTS_NORM.get(base_norm, []):
                    if repl in provisions_index:
                        prov = provisions_index[repl]
                        used_key = repl
                        break
    
            if prov:
                dispo = float(prov.get("quantity", 0))
                used = min(float(val), dispo)
                reste = max(0.0, float(val) - dispo)
    
                # Ce qu'il reste à acheter
                if reste <= FLOAT_EPS:
                    del items[label]
                else:
                    data["val"] = round(reste, 2)
    
                if used > FLOAT_EPS:
                    consommation_totale[used_key] += used
                    entry = pantry_used.get(used_key)
                    if not entry:
                        pantry_label = pretty_from_norm(used_key)
                        entry = {
                            "label": pantry_label, "val": 0.0, "unit": data["unit"],
                            "indispensable": indispensables_map.get(used_key, False),
                            "recipes": set(),
                        }
                        pantry_used[used_key] = entry
                    entry["val"] += used
                    entry["recipes"].update(data.get("recipes", []))
    
    #arrondir les affichages pour ne pas avoir trop de décimales
    def _fmt_amount(val, unit):
        if val is None:
          return ""
        u = (unit or "").lower()
    
        # règles simples :
        # - kg / l : 2 décimales max
        # - g : entier
        # - pièces : entier
        if u in ("kg", "l"):
            s = f"{float(val):.2f}".rstrip("0").rstrip(".")
        elif u.startswith("g"):
            s = str(int(round(float(val))))
        elif u.startswith(("pièce", "piece")):
            s = str(int(round(float(val))))
        else:
            # défaut : 2 décimales max
            s = f"{float(val):.2f}".rstrip("0").rstrip(".")
        return f"{s} {unit}".strip()
    
    
    # --- AFFICHAGE COURSES ---
    if update_provisions:
        update_provisions_files(consommation_totale, data_dir)
    return {
        'liste_courses': liste_courses,
        'consommation_totale': dict(consommation_totale),
        'pantry_used': pantry_used,
    }

def update_provisions_files(consommation_totale: dict, data_dir: str | Path):
    """Décrémente provisions.txt et génère courses_placard.txt (comme la cellule 3)."""
    init(data_dir)
    # code notebook
    # ----- DÉCRÉMENTER LES PROVISIONS & GÉNÉRER courses_placard.txt -----
    for ing_norm, used in consommation_totale.items():
        prov = provisions_index.get(ing_norm)
        if prov:
            prov["quantity"] = max(0, float(prov.get("quantity", 0)) - float(used))
    
    courses_placard = []
    for prov in provisions_index.values():
        qte = float(prov.get("quantity", 0))
        qte_min = float(prov.get("quantity_min", 0))
        if qte < qte_min:
            courses_placard.append({"name": prov["name"], "quantity": round(qte_min - qte, 2)})
    
    with open(provisions_path, "w", encoding="utf-8") as f:
        json.dump(list(provisions_index.values()), f, ensure_ascii=False, indent=2)
    
    courses_placard_path = DATA_DIR / "courses_placard.txt"
    with open(courses_placard_path, "w", encoding="utf-8") as f:
        json.dump(courses_placard, f, ensure_ascii=False, indent=2)
    
    print(f"→ Placard mis à jour : {provisions_path.resolve()}")
    print(f"→ Réappro placard : {courses_placard_path.resolve()}")
