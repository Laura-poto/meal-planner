# app.py
from pathlib import Path
import streamlit as st
import pandas as pd

import engine

st.set_page_config(page_title="Meal Planner", layout="wide")
st.title("🍽️ Meal Planner")

DATA_DIR = Path("data")

# 1) Matching (comme le notebook) — sans aucun paramètre inutile
match = engine.compute_matching(DATA_DIR)

st.subheader("📊 Matching des recettes (marché / placard)")
left, right = st.columns([2, 1])

with left:
    if match["scored_filtered"]:
        df = pd.DataFrame(match["scored_filtered"])
        cols = [c for c in ["category","name","score_market","score_pantry","manque_market","manque_pantry","link"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, height=520)
    else:
        st.info("Aucune recette ne passe les filtres actuels (MATCH_MIN/MATCH_MIN_PANTRY).")

with right:
    st.markdown("**Affichage texte (comme le notebook)**")
    with st.expander("Voir / masquer"):
        st.code(match["text"], language="text")
    if match["unknown_ingredients"]:
        st.warning("Ingrédients non définis dans ingredients_infos.txt :\n- " + "\n- ".join(match["unknown_ingredients"]))

# 2) Choix recettes + personnes (comme tu avais déjà)
st.subheader("✅ Choisir les recettes à cuisiner")

names = [r["name"] for r in match["scored_all"]]
selection = st.multiselect("Recettes", options=names, default=[])

personnes = st.number_input("Nombre de personnes", min_value=1, max_value=10, value=4, step=1)

if st.button("Générer les courses"):
    if not selection:
        st.error("Choisis au moins une recette.")
    else:
        out = engine.courses(DATA_DIR, selection, int(personnes))
        st.success("Courses générées.")
        st.json(out["courses_raw"])
