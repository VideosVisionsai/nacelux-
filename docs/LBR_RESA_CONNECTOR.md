# Connecteur LBR / RESA (Luxembourg) — Spécification & Statut

> **STATUT DE CONFORMITÉ : `REQUIRES OFFICIAL CONFIRMATION`**  
> Ce connecteur n'utilise **aucune API REST officielle documentée** par l'État luxembourgeois car aucune API publique ouverte n'est mise à disposition par le G.I.E. LBR.  
> Toute utilisation en production doit faire l'objet d'une convention d'accès B2B ou respecter scrupuleusement les limitations techniques et légales ci-dessous.

---

## 1. Méthode Actuelle d'Ingestion (Passerelle Publique Contrôlée)

Le connecteur accède uniquement aux URLs canoniques des publications publiques journalières du RESA :
`https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-YYYY_SEQ_...`

1. **Validation d'URL & Protocole** : Vérification stricte du domaine `www.lbr.lu`, schéma `https` obligatoire.
2. **Respect de `robots.txt`** : Vérification systématique avant chaque tentative. Le chemin `publication-journal` est autorisé pour la consultation publique.
3. **HTTP First $\to$ Headless Browser Fallback** : Tentative de lecture HTML statique ; bascule sur Playwright uniquement si le rendu DOM JavaScript est exigé.
4. **Détection CAPTCHA (Friendly Captcha)** : Détection passive. **Aucun contournement, solver ou bypass n'est implémenté**. Si le Captcha bloque le rendu, le run est immédiatement consigné comme `BLOCKED` / `CAPTCHA_REQUIRED` et s'arrête proprement.
5. **Rate-Limiting & Espacement** : Délai minimum de 8 secondes entre requêtes consécutives (`LBR_RESA_MIN_INTERVAL_SECONDS`).
6. **User-Agent Identifiable** : `NACELUX/1.0 (+https://votre-domaine.lu/data-policy; contact@votre-domaine.lu)`.
7. **Conservation des Preuves & Empreinte** : SHA-256 de chaque document PDF téléchargé avec stockage immuable dédupliqué et trace d'audit complète.

---

## 2. Limites & Risques Techniques

* **Instabilité UI** : Toute modification du DOM de l'interface `mjrcs-web-front` par le LBR peut altérer la détection des lignes.
* **Blocages IP / WAF** : En cas de trafic trop soutenu, l'infrastructure du LBR peut élever le niveau de challenge Friendly Captcha.
* **Volume** : Limité aux publications du jour ou consultées à la demande.

---

## 3. Démarche pour Passage en Production B2B Certifiée

Pour une exploitation commerciale à grande échelle sans dépendance à l'interface HTML :
1. **Convention B2B LBR** : Souscrire à l'accès professionnel officiel proposé par le G.I.E. Registre de Commerce et des Sociétés.
2. **Accès EDI / Flux Direct** : Remplacer l'adaptateur de parsing HTML par le connecteur certifié LBR une fois les identifiants de passerelle délivrés.

---

## 4. Modèle de Données & Tables Associées

* `resa_journals` : Clé du journal, date, séquence, hash du contenu.
* `resa_entries` : Ligne extraite, dénomination, numéro RCS, extrait légal, statut de changement (`NEW`, `UPDATED`, `UNCHANGED`).
* `resa_documents` : Lien de téléchargement, SHA-256, statut d'extraction et de stockage.
* `resa_sync_runs` : Trace d'exécution auditable (date, méthode, captcha, robots, erreurs).
