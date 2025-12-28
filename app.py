from pathlib import Path
import streamlit as st
import pandas as pd
import unicodedata
import engine


def _upper_no_accents(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.upper()

def format_courses(liste_courses: dict) -> str:
    """
    Transforme la structure dict {rayon: {label: {val, unit, recipes, ...}}}
    en texte lisible style notebook.
    """
    lines = []
    # ordre de rayons : Marché en premier si présent, sinon tri alpha
    rayons = list(liste_courses.keys())
    rayons_sorted = sorted(rayons, key=lambda r: (0 if r.lower() in ["marché","marche"] else 1, r.lower()))
    for rayon in rayons_sorted:
        header = _upper_no_accents(rayon)
        lines.append(header)
        items = liste_courses[rayon] or {}
        # tri : indispensable d'abord, puis alpha
        def _k(item):
            label, d = item
            return (0 if d.get("indispensable") else 1, label.lower())
        for label, d in sorted(items.items(), key=_k):
            val = d.get("val")
            unit = d.get("unit") or ""
            if val is None:
                qty = ""
            else:
                qty = f"{val}{unit}".replace(" ", "")
            recipes = d.get("recipes") or []
            n = len(recipes)
            recettes_txt = " / ".join(recipes)
            lines.append(f"{label} : {qty}  — dans : {n} recette(s) ({recettes_txt})")
        lines.append("")  # blank line
    return "\n".join(lines).strip()


st.set_page_config(page_title="Meal Planner", layout="wide")
st.title("🍽️ Meal Planner")

DATA_DIR = Path("data")

# 1) Matching
match = engine.compute_matching(DATA_DIR)

st.subheader("📊 Matching des recettes (marché / placard)")
col1, col2 = st.columns([2, 1])

with col1:
    df = pd.DataFrame(match["scored"])
    if df.empty:
        st.info("Aucune recette ne passe les filtres actuels (MATCH_MIN / MATCH_MIN_PANTRY).")
    else:
        cols = [c for c in ["category","name","score_market","score_pantry","manque_market","manque_pantry","link"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, height=520)

with col2:
    with st.expander("Voir l'affichage texte (comme dans le notebook)"):
        st.code(match["text"], language="text")
    if match["unknown_ingredients"]:
        st.warning("Ingrédients non définis dans ingredients_infos.txt :\n- " + "\n- ".join(match["unknown_ingredients"]))

st.divider()

# 2) Choix + courses
st.subheader("✅ Choisir les recettes et générer les courses")

options = [r["name"] for r in match["scored"]]  # on propose les recettes filtrées
selection = st.multiselect("Recettes", options=options, default=[])

personnes = st.number_input("Nombre de personnes", min_value=1, max_value=12, value=4, step=1)
update_prov = st.checkbox("Mettre à jour le placard (provisions.txt) et générer courses_placard.txt", value=False)

if st.button("Générer les courses"):
    if not selection:
        st.error("Choisis au moins une recette.")
    else:
        out = engine.compute_courses(DATA_DIR, selection, int(personnes), update_provisions=update_prov)
        st.success("Courses générées.")
        st.text(format_courses(out["liste_courses"]))
        with st.expander("Voir la version JSON (debug)"):
            st.json(out["liste_courses"])
        with st.expander("Voir détails placard (consommation / utilisé)"):
            st.json(out["pantry_used"])
