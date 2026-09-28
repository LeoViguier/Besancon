# Sorties Besançon → Discord

Agrégateur des nouveaux événements (concerts, spectacles, expos, festivals, visites…)
à Besançon, dans le Doubs et en Bourgogne-Franche-Comté. Chaque nouveauté est
annoncée dans un salon Discord via un webhook.

## Comment les événements sont récupérés

| Type | Principe | IA ? | Exemple configuré |
|---|---|---|---|
| `openagenda` | API publique [OpenAgenda](https://openagenda.com) via Opendatasoft : des milliers d'agendas (mairies, médiathèques, musées, offices de tourisme…), données propres, filtrables par zone | non | Besançon + 40 km, Doubs, région |
| `jsonld` | Données `schema.org/Event` intégrées aux pages pour Google (billetteries, agendas) ; peut suivre les liens vers les fiches | non | jds.fr Besançon |
| `ical` / `rss` | Flux standards | non | – |
| `ai` | N'importe quelle page : Claude lit le texte et en extrait les événements au format JSON imposé | oui | La Rodia, Les 2 Scènes, Office de tourisme, besac.com |

**En résumé :** l'essentiel se fait sans IA (OpenAgenda est la meilleure source,
et beaucoup de sites exposent du JSON-LD). L'IA sert de solution de repli pour les
sites qui n'ont que du HTML « à lire », comme les pages de programmation des salles.
Claude n'est appelé que lorsque le contenu d'une page a changé, pour limiter le coût.

Les sources IA sont ignorées si `ANTHROPIC_API_KEY` n'est pas défini : l'agrégateur
fonctionne très bien sans.

## Fonctionnement

1. Chaque source est interrogée (une source en panne n'empêche pas les autres).
2. Filtrage : événements passés, à plus d'un an, ou contenant un mot exclu
   (`recrutement`, `job dating`, `France Travail`…, voir `config.yaml`).
3. Dédoublonnage entre sources (même titre normalisé + même jour).
4. Envoi des nouveautés sur Discord (10 par message, 40 max par passage, le reste
   au passage suivant).
5. Mémorisation dans `state/seen.json`, versionné dans le dépôt.

Lorsqu'une source est interrogée pour la première fois (premier lancement ou
ajout dans la config), ses événements existants sont mémorisés **sans être envoyés**,
pour ne pas inonder le salon ; seules les nouveautés suivantes sont annoncées.

## Mise en route (GitHub Actions, gratuit)

1. Dans le dépôt GitHub : **Settings → Secrets and variables → Actions → New repository secret**
   - `DISCORD_WEBHOOK_URL` : l'URL du webhook Discord (ne jamais la mettre dans le code)
   - `ANTHROPIC_API_KEY` *(facultatif)* : active les sources `ai`
2. Fusionner sur la branche par défaut (les tâches planifiées ne tournent que là).
3. **Actions → Agrégateur d'événements → Run workflow** pour un premier lancement
   (cocher « Simulation » pour voir ce qui serait envoyé sans rien envoyer).

Ensuite le workflow tourne toutes les 3 heures, de 8h à 23h environ (heure de Paris).

## En local

```bash
pip install -r requirements.txt
python -m besancon_events --dry-run          # affiche les nouveautés sans rien envoyer
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... python -m besancon_events
python -m pytest -q                          # tests
```

## Ajouter une source

Dans `config.yaml`, par exemple :

```yaml
  citadelle:
    type: ai
    urls: [https://www.citadelle.com/fr/agenda]

  un-site-avec-json-ld:
    type: jsonld
    urls: [https://exemple.fr/agenda/]
    follow_links: "exemple\\.fr/evenement/"   # facultatif : visiter les fiches

  openagenda-jura:
    type: openagenda
    departments: [Jura]
```

Pour savoir si un site expose du JSON-LD, chercher `application/ld+json` et
`"Event"` dans le code source de la page. Si oui, préférer `jsonld` à `ai`.

## Coût de l'IA

Modèle par défaut : `claude-opus-5-5` (réglable par source avec `model:`), effort
bas. Une page d'agenda fait de l'ordre de 10 000 à 25 000 tokens ; comme l'appel
n'a lieu que si la page a changé, compter quelques centimes par source et par jour.
Pour réduire encore : `model: claude-haiku-4-5`, ou moins de sources `ai`.
