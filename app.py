from pathlib import Path
import streamlit as st
import pandas as pd
import engine

st.set_page_config(page_title="Meal Planner", layout="wide")
st.title("🍽️ Meal Planner")

DATA_DIR = Path("data")

match = engine.compute_matching(DATA_DIR)

st.subheader("📊 Matching des recettes (comme le notebook)")
col1, col2 = st.columns([2, 1])

with col1:
    df = pd.DataFrame(match["scored"])
    if len(df) == 0:
        st.info("Aucune recette ne passe les filtres actuels.")
    else:
        cols = [c for c in ["category","name","score_market","score_pantry","manque_market","manque_pantry","link"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, height=520)

with col2:
    with st.expander("Voir l'affichage texte (comme dans Jupyter)", expanded=False):
        st.code(match["text"], language="text")

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
        st.json(out)
