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
        lines.append(f"**{header}**")
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
                qty = f"{val} {unit}".strip()
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

df = pd.DataFrame(match["scored"])

# Renommage colonnes (voir section suivante)
df = df.rename(columns={
    "category": "catégorie",
    "name": "nom",
    "score_market": "taux de match marché",
    "score_pantry": "taux de match placard",
    "ok_market": "OK marché",
    "ok_pantry": "OK placard",
    "manque_market": "manque marché",
    "manque_pantry": "manque placard",
})

cols = ["catégorie", "nom", "taux de match marché", "taux de match placard", "OK marché", "OK placard", "manque marché", "manque placard", "link"]
cols = [c for c in cols if c in df.columns]  # sécurité

cols_sub = [c for c in cols if c != "catégorie"]  # la catégorie sera dans le sous-titre, pas dans le tableau
order_map = {c.casefold(): i for i, c in enumerate(engine.CATEGORY_ORDER)}
categories = sorted(
    df["catégorie"].dropna().unique(),
    key=lambda c: (order_map.get(str(c).casefold(), 999), str(c).casefold())
)

for cat in categories:
    st.markdown(f"### {cat.upper()}") 
    sdf = df[df["catégorie"] == cat]

    # hauteur auto (évite un gros tableau vide)
    h = min(520, 38 * (len(sdf) + 1) + 20)

    st.data_editor(
        sdf[cols_sub],
        use_container_width=True,
        height=h,
        disabled=True,
        column_config={
            "link": st.column_config.LinkColumn("lien"),
        },
        key=f"table_{str(cat).casefold()}",
    )

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
        st.markdown(format_courses(out["liste_courses"]).replace("\n", "  \n"))
        with st.expander("Voir la version JSON (debug)"):
            st.json(out["liste_courses"])
        with st.expander("Voir détails placard (consommation / utilisé)"):
            st.json(out["pantry_used"])
