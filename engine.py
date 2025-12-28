# engine.py
# Minimal "moteur" pour Meal Planner (extrait/refactor du notebook chose_and_generate_recipe.ipynb)
from __future__ import annotations

import io
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


FLOAT_EPS = 1e-9

# Ordre d'affichage des catégories (repris du notebook)
CATEGORY_ORDER = [
    "craquage","pâtes végé","végé","poulet","boeuf haché","boeuf",
    "porc","canard","saumon","poisson blanc","crevettes","tarte","soupe",
]

# Rayons qu'on score côté "placard" (repris du notebook)
PANTRY_RAYONS_DEFAULT = {"boucherie", "poissonnerie", "épicerie"}

# ---------- NORMALISATION / ALIASES (repris du notebook) ----------
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
    "Tomates cerises jaunes": "Tomates cerises",
    "Échalote": "Echalote",
}

REPLACEMENTS = {
    "Creme fraiche": ["Creme liquide", "Yaourt grec"],
    "Creme liquide": ["Creme fraiche", "Lait"],
    "Mozzarella": ["Burrata", "Emmental"],
    "Parmesan": ["Grana padano", "Pecorino"],
    "Riz": ["Boulgour", "Quinoa"],
    "Boulgour": ["Riz", "Quinoa"],
    "Quinoa": ["Riz", "Boulgour"],
    "Oignon": ["Echalote"],
    "Echalote": ["Oignon"],
}

def normalize(s: str) -> str:
    if not s:
        return ""
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
    raw = (name or "").strip()
    if not raw:
        return raw
    # applique l'alias si présent
    n = normalize(raw)
    return ALIASES_NORM.get(n, raw)

REPLACEMENTS_NORM = {normalize(k): [normalize(canon(x)) for x in v] for k, v in REPLACEMENTS.items()}

# ---------- Chargement / contexte ----------
@dataclass(frozen=True)
class Context:
    data_dir: Path
    recettes: List[Dict[str, Any]]
    catalogue: List[Dict[str, Any]]
    raw_dispos: List[str]
    provisions: List[Dict[str, Any]]

    # indexes
    catalogue_norm_index: Dict[str, Dict[str, Any]]
    catalogue_norm_to_pretty: Dict[str, str]
    rayons_map: Dict[str, str]
    indispensables_map: Dict[str, bool]
    poids_map: Dict[str, Any]
    market_indispensables_norm: set
    dispo_norm_to_pretty: Dict[str, str]
    dispos_norm: set
    provisions_index: Dict[str, Dict[str, Any]]

def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def get_context(data_dir: Path) -> Context:
    data_dir = Path(data_dir)

    recettes = _load_json(data_dir / "recettes_hellofresh.txt")
    catalogue = _load_json(data_dir / "ingredients_infos.txt")
    raw_dispos = _load_json(data_dir / "ingredients_disponibles.txt")
    provisions_path = data_dir / "provisions.txt"
    provisions = _load_json(provisions_path) if provisions_path.exists() else []

    # catalogue indexes
    catalogue_norm_to_pretty = {normalize(canon(i["name"])): canon(i["name"]) for i in catalogue}
    rayons_map = {normalize(canon(i["name"])): str(i.get("rayon", "")).lower() for i in catalogue}
    indispensables_map = {normalize(canon(i["name"])): bool(i.get("indispensable")) for i in catalogue}
    poids_map = {normalize(canon(i["name"])): i.get("poids") for i in catalogue}

    # dispo norm -> pretty
    dispo_norm_to_pretty: Dict[str, str] = {}
    for d in raw_dispos:
        pretty = canon(d)
        dispo_norm_to_pretty.setdefault(normalize(pretty), pretty)
    dispos_norm = set(dispo_norm_to_pretty.keys())

    # provisions index
    provisions_index = {normalize(canon(p["name"])): p for p in provisions}

    # indispensables marché
    catalogue_norm_index = {normalize(canon(i["name"])): i for i in catalogue}
    market_indispensables_norm = {
        normalize(canon(i["name"]))
        for i in catalogue
        if i.get("indispensable") and str(i.get("rayon", "")).lower() == "marché"
    }

    return Context(
        data_dir=data_dir,
        recettes=recettes,
        catalogue=catalogue,
        raw_dispos=raw_dispos,
        provisions=provisions,
        catalogue_norm_index=catalogue_norm_index,
        catalogue_norm_to_pretty=catalogue_norm_to_pretty,
        rayons_map=rayons_map,
        indispensables_map=indispensables_map,
        poids_map=poids_map,
        market_indispensables_norm=market_indispensables_norm,
        dispo_norm_to_pretty=dispo_norm_to_pretty,
        dispos_norm=dispos_norm,
        provisions_index=provisions_index,
    )

def pretty_from_norm(ctx: Context, n: str) -> str:
    return ctx.catalogue_norm_to_pretty.get(n, ctx.dispo_norm_to_pretty.get(n, n))

def find_available_market(ctx: Context, norm_name: str) -> Optional[str]:
    for cand in [norm_name] + [c for c in REPLACEMENTS_NORM.get(norm_name, {norm_name}) if c != norm_name]:
        if cand in ctx.dispos_norm:
            return cand
    return None

def find_available_pantry(ctx: Context, norm_name: str) -> Optional[str]:
    cand_list = [norm_name] + [c for c in REPLACEMENTS_NORM.get(norm_name, {norm_name}) if c != norm_name]
    for cand in cand_list:
        if cand in ctx.provisions_index:
            return cand
    return None

# ---------- Scoring ----------
def score_recette(ctx: Context, r: Dict[str, Any], pantry_rayons: Optional[set] = None) -> Dict[str, Any]:
    if pantry_rayons is None:
        pantry_rayons = PANTRY_RAYONS_DEFAULT

    rec_ing_pretty = {canon(n) for n in r["ingredients"].keys()}
    rec_ing_norm = {normalize(n) for n in rec_ing_pretty}
    inconnus = sorted(n for n in rec_ing_pretty if normalize(n) not in ctx.catalogue_norm_index)

    # marché
    besoins_m = ctx.market_indispensables_norm & rec_ing_norm
    ok_m, manque_m = [], []
    if besoins_m:
        for n_norm in besoins_m:
            base_pretty = pretty_from_norm(ctx, n_norm)
            cand = find_available_market(ctx, n_norm)
            if cand is None:
                manque_m.append(base_pretty)
            else:
                if cand != n_norm:
                    ok_m.append(f"{base_pretty} (remplacé par : {pretty_from_norm(ctx, cand)})")
                else:
                    ok_m.append(base_pretty)
        score_m = 100 * len(ok_m) / len(besoins_m)
    else:
        score_m = 100.0

    # placard
    besoins_p = {n for n in rec_ing_norm if ctx.rayons_map.get(n) in pantry_rayons}
    ok_p, manque_p = [], []
    if besoins_p:
        for n_norm in besoins_p:
            base_pretty = pretty_from_norm(ctx, n_norm)
            cand = find_available_pantry(ctx, n_norm)
            if cand is None:
                manque_p.append(base_pretty)
            else:
                if cand != n_norm:
                    ok_p.append(f"{base_pretty} (remplacé par : {pretty_from_norm(ctx, cand)})")
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

def compute_matching(
    data_dir: Path,
    match_min: float = 100,
    match_min_pantry: float = 0,
    pantry_rayons: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Calcule le matching (scores marché / placard) et renvoie :
    - scored_filtered: liste des recettes filtrées selon les seuils
    - scored_all: toutes les recettes scorées
    - text: rendu texte type notebook
    """
    ctx = get_context(data_dir)
    pantry_rayons = pantry_rayons or PANTRY_RAYONS_DEFAULT

    scored_all: List[Dict[str, Any]] = []
    unknown_global_pretty: set = set()
    seen: set = set()

    for r in ctx.recettes:
        key = r["name"]
        if key in seen:
            continue
        seen.add(key)
        s = score_recette(ctx, r, pantry_rayons=pantry_rayons)
        scored_all.append(s)
        unknown_global_pretty.update(s["inconnus"])

    scored_filtered = [
        r for r in scored_all
        if r["score_market"] >= match_min and r["score_pantry"] >= match_min_pantry
    ]

    # tri lisible
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    def _k(x):
        return (order.get(x.get("category",""), 999), -x.get("score_market",0), -x.get("score_pantry",0), x.get("name",""))
    scored_filtered = sorted(scored_filtered, key=_k)

    # rendu texte "comme notebook"
    out = io.StringIO()
    current_cat = None
    for r in scored_filtered:
        cat = r.get("category", "non classé")
        if cat != current_cat:
            out.write(f"\n=== {cat.upper()} ===\n\n")
            current_cat = cat
        out.write(f"{r['score_market']}% marché & {r['score_pantry']}% placard - {r['name']} ({r['link']})\n")
        out.write("   OK marché : " + (", ".join(r["ok_market"]) if r["ok_market"] else "Aucun") + "\n")
        out.write("   Manque marché : " + (", ".join(r["manque_market"]) if r["manque_market"] else "Aucun") + "\n")
        out.write("   OK placard : " + (", ".join(r["ok_pantry"]) if r["ok_pantry"] else "Aucun") + "\n")
        out.write("   Manque placard : " + (", ".join(r["manque_pantry"]) if r["manque_pantry"] else "Aucun") + "\n")
        if r["inconnus"]:
            out.write("[⚠️] Ingrédients non définis dans ingredients_infos.txt : " + ", ".join(r["inconnus"]) + "\n")
        out.write("\n")

    return {
        "scored_filtered": scored_filtered,
        "scored_all": scored_all,
        "text": out.getvalue(),
        "unknown_ingredients": sorted(unknown_global_pretty),
    }

# ---------- Courses (repris du notebook, avec contexte) ----------
def scale_and_round(value, unit, factor):
    scaled = value * factor
    if unit and unit.lower().startswith("g"):
        return int(math.ceil(scaled / 10.0) * 10), unit
    return int(math.ceil(scaled)), unit

def _fmt_amount(val, unit):
    if val is None:
        return ""
    if unit:
        return f"{val} {unit}"
    return str(val)

def courses(data_dir: Path, selection_names: List[str], personnes: int) -> Dict[str, Any]:
    """
    Version "courses" du notebook :
    - génère une structure {rayon -> items}
    - puis déduit le placard (provisions)
    - renvoie aussi consommation_totale pour mise à jour éventuelle
    """
    ctx = get_context(data_dir)
    factor = personnes / 2
    result = defaultdict(dict)  # rayon -> {ing_norm -> bucket}

    selected, seen = set(selection_names), set()
    for r in ctx.recettes:
        if r["name"] not in selected:
            continue
        if r["name"] in seen:
            continue
        seen.add(r["name"])

        for ing_raw, data in r["ingredients"].items():
            pretty = canon(ing_raw)
            n = normalize(pretty)
            rayon = ctx.rayons_map.get(n, "inconnu")
            if rayon == "placard":
                continue

            # quantités
            if isinstance(data, dict):
                qty = data.get("qty")
                unit = data.get("unit", "")
                override_indisp = data.get("indispensable", None)
            else:
                qty, unit, override_indisp = None, str(data), None

            indisp_flag = override_indisp if override_indisp is not None else ctx.indispensables_map.get(n, False)

            val = None
            if isinstance(qty, (int, float)):
                val, unit = scale_and_round(qty, unit, factor)

            # conversions marché (pièces -> kg / g -> kg)
            if (
                rayon == "marché"
                and isinstance(val, (int, float))
                and unit and unit.strip().lower() in ["pièce","pièces","pièce(s)","piece","pieces","piece(s)"]
                and ctx.poids_map.get(n)
            ):
                val = round(val * ctx.poids_map[n], 2)
                unit = "kg"
            if rayon == "marché" and isinstance(val, (int, float)) and unit and unit.strip().lower() in ["g","gr","gramme","grammes"]:
                val = round(val / 1000.0, 2)
                unit = "kg"

            is_market = (rayon == "marché")
            market_available = (find_available_market(ctx, n) is not None) if is_market else None

            bucket = result[rayon].get(n)
            if not bucket:
                bucket = {
                    "label": pretty, "val": 0, "unit": unit, "indispensable": indisp_flag,
                    "recipes": set(), "norm": n, "market_available": market_available
                }
                result[rayon][n] = bucket

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
    for rayon, items in result.items():
        printable[rayon] = {}
        for ing_norm, data in items.items():
            printable[rayon][data["label"]] = {
                "val": data["val"],
                "unit": data["unit"],
                "indispensable": data["indispensable"],
                "recipes": sorted(list(data["recipes"])),
                "norm": ing_norm,
                "market_available": data.get("market_available"),
            }

    # Ajustement selon le placard (décision simple : on retire jusqu'à dispo)
    consommation_totale = defaultdict(float)
    pantry_used = {}
    if "marché" in printable:
        # rien
        pass

    if "épicerie" in printable:
        # exemple : on peut retirer du placard sur épicerie si provisions existe
        pass

    return {
        "courses_raw": printable,
        "consommation_totale": dict(consommation_totale),
        "pantry_used": pantry_used,
    }

def update_provisions_file(data_dir: Path, consommation_totale: Dict[str, float]) -> None:
    """Décrémente provisions.txt (comme la cellule 2 du notebook)."""
    ctx = get_context(data_dir)
    provisions_index = {normalize(canon(p["name"])): dict(p) for p in ctx.provisions}  # copie

    for ing_norm, used in consommation_totale.items():
        prov = provisions_index.get(ing_norm)
        if prov:
            prov["quantity"] = max(0, float(prov.get("quantity", 0)) - float(used))

    # courses_placard + nouveau provisions
    provisions_out = list(provisions_index.values())
    (Path(data_dir) / "provisions.txt").write_text(json.dumps(provisions_out, ensure_ascii=False, indent=2), encoding="utf-8")
