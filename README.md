# WebChronicle

WebChronicle est un service d’archivage web pour conserver des copies horodatées de pages publiques, avec recherche, capture visuelle et mode lecture.

## Fonctions
- Soumettre une URL publique à archiver
- Capture HTML rendue côté serveur avec Playwright
- Extraction du titre et du texte lisible
- Capture d’écran PNG
- URL courte de snapshot
- Historique par URL
- Recherche simple dans les archives
- Flux RSS des dernières captures
- Import générique de flux RSS/XML pour migration de métadonnées
- Protection SSRF basique (localhost, IP privées et schémas non HTTP(S) bloqués)

## Limite volontaire
WebChronicle n’essaie pas de contourner les paywalls, connexions, CAPTCHA, anti-bot ou autres contrôles d’accès.

## Développement local

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Par défaut, le frontend utilise `http://localhost:8000`.

## Déploiement recommandé

### 1. Backend sur Render
Le dépôt contient `render.yaml` et `backend/Dockerfile`.

Dans Render :
1. **New +** → **Blueprint** (ou Web Service depuis GitHub)
2. sélectionner le dépôt `WEBCHRONICLE`
3. définir :
   - `CORS_ORIGINS=https://<votre-site>.netlify.app`
   - `FRONTEND_URL=https://<votre-site>.netlify.app`
   - `PUBLIC_BASE_URL=https://<votre-api>.onrender.com`
4. déployer

### 2. Frontend sur Netlify
Le fichier `netlify.toml` configure automatiquement :
- base : `frontend`
- build : `npm run build`
- publication : `frontend/dist`

Dans Netlify, ajouter la variable :

```text
VITE_API_URL=https://<votre-api>.onrender.com
```

Puis relancer le déploiement.

## À savoir sur le stockage Render
Cette version utilise SQLite et le disque local pour les snapshots/captures. Sur un service sans disque persistant, les données peuvent être perdues après un redéploiement ou un redémarrage. Pour un service d’archives durable, prévoir ensuite une base PostgreSQL et un stockage objet/persistant.
