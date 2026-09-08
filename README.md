# Elden Death Counter

Compteur de morts automatique pour Elden Ring, à afficher en direct dans OBS ou
Streamlabs. Deux compteurs à l'écran : le total depuis le début, et le nombre de
morts sur le boss en cours, que tu remets à zéro d'une touche quand tu le bats.

La détection lit uniquement l'image affichée à l'écran. Aucune lecture mémoire,
aucun hook dans le processus du jeu : rien qui puisse intéresser l'anti-triche.

## Installation

**Sans Python.** Télécharge `elden-counter.exe` dans les
[Releases](../../releases) et pose-le où tu veux.

**Avec Python 3.10 ou plus récent :**

```
pip install elden-death-counter
```

## Prise en main

```
elden-counter setup          # une seule fois
elden-counter run --boss "Malenia"
```

Le setup te demande de mourir une fois et d'appuyer sur F8 pendant que le texte
est affiché. L'image capturée sert de référence pour toutes les détections
suivantes. C'est ce qui rend l'outil indépendant de ta résolution, de ton ratio
d'écran et de la langue de ton jeu.

Ajoute ensuite dans OBS une **source navigateur** sur `http://127.0.0.1:4747`,
en 600×300, largeur et hauteur personnalisées. Le fond est transparent, tu
positionnes et redimensionnes la source comme tu veux.

## Raccourcis pendant le stream

| Touche | Effet |
|---|---|
| F9 | Ajouter une mort aux deux compteurs |
| F10 | En retirer une |
| F11 | Remettre le compteur du boss à zéro, le total reste intact |
| F12 | Boss vaincu : le score part dans l'historique et le compteur repart de zéro |

## Autres commandes

```
elden-counter boss "Radagon"   # changer le boss affiché
elden-counter history          # revoir tes scores sur les boss battus
elden-counter reset            # remettre le boss à zéro
elden-counter reset --all      # tout effacer, historique compris
```

## Réglages

`elden-counter diagnose` enregistre pendant trente secondes ce que voit le
détecteur.

Les seuils par défaut ont été réglés sur de vraies captures d'Elden Ring, pas
estimés : sur ces mesures, une mort obtient au minimum 0,78 et le jeu normal
ne dépasse jamais 0,35, d'où le seuil à 0,55. Si l'écart est plus faible chez
toi, refais le setup en mourant à des endroits vraiment différents.

`--threshold` ajuste le seuil de déclenchement, `--confirm` le nombre d'images
consécutives requises. Monte `--confirm` si tu as des faux positifs, descends-le
si des morts passent à travers. Vérifie l'aperçu généré par le setup
avant de toucher aux seuils : les pixels surlignés doivent dessiner le
texte et rien d'autre.

Sur un écran secondaire, précise `--monitor 2`.

## Ce qui peut poser problème

Le HDR délave les captures sur certaines configurations Windows. Si les scores
sont anormalement bas, refais le setup HDR activé pour que la référence et
l'analyse soient cohérentes.

Sous Windows, les raccourcis clavier globaux demandent souvent de lancer le
terminal en administrateur.

Sur console via carte d'acquisition, fais le setup avec la fenêtre de preview
dans la position exacte où elle restera pendant le stream.

## Licence

MIT.
