# Super Thermostat

Intégration Home Assistant (**version 1.0**) pour piloter chauffage, clim et vannes thermostatiques **depuis l'interface, sans YAML**. Elle reprend le moteur du plugin *Thermostat* de Jeedom (régulation avec anticipation sur la température extérieure et **auto-apprentissage**) et le sépare en deux rôles : des **zones** qui calculent des pourcentages, et des **gestionnaires** qui pilotent les appareils.

![Schéma de fonctionnement](docs/schema.svg)

**En 30 secondes**

1. **Mesures** : la température de la pièce et de l'extérieur, les fenêtres, la saison, le poêle à bois. La *fraction chaudière* dit quelle part de la chaleur vient de la chaudière : 0 % quand il fait doux, 100 % quand il fait froid.
2. **Zone** (une par pièce) : elle a deux consignes, chauffe et froid, et calcule des pourcentages. Elle ne commande aucun appareil.
3. **Gestionnaires** : la chaudière additionne les pourcentages, la clim les suit, les vannes s'ouvrent selon la demande.
4. **Appareils** : brûleur et circulateur, clim réversible, vannes thermostatiques.

> Prérequis : Home Assistant **2026.10** ou plus récent.

---

## Sommaire

1. [Installation](#installation)
2. [Mise en route pas à pas](#mise-en-route-pas-à-pas)
3. [Les quatre types d'entrées](#les-quatre-types-dentrées)
   - [Zone](#1-zone) (dont les [vannes thermostatiques](#vannes-thermostatiques), le [poêle à bois](#poêle-à-bois) et les [notifications de défaillance](#notifications-de-défaillance))
   - [Fraction chaudière](#2-fraction-chaudière)
   - [Gestion chaudière](#3-gestion-chaudière)
   - [Gestion clim](#4-gestion-clim)
4. [Comment ça calcule](#comment-ça-calcule)
5. [Exemples](#exemples)
6. [Dépannage](#dépannage)
7. [Sécurité et limites](#sécurité-et-limites)
8. [Historique des versions](#historique-des-versions)
9. [Crédits et licence](#crédits-et-licence)

---

## Installation

### Manuelle ou avec git

1. Copier le dossier `custom_components/super_thermostat/` dans `/config/custom_components/` de Home Assistant.
2. Redémarrer Home Assistant.
3. Aller dans **Paramètres → Appareils et services → Ajouter une intégration → Super Thermostat**.

Avec un dépôt git (`https://github.com/Maxime-roche/super_thermostat`), il suffit de cloner ou de tirer (`git pull`) le dépôt dans `/config` puis de redémarrer. Le bouton **?** de l'intégration (Paramètres → Appareils et services) ouvre cette page.

### HACS (dépôt personnalisé)

**HACS → ⋮ → Dépôts personnalisés**, ajouter `https://github.com/Maxime-roche/super_thermostat` avec la catégorie *Intégration*, puis installer et redémarrer.

### Mise à jour

Remplacer le dossier `custom_components/super_thermostat/`, redémarrer. Les coefficients appris, les consignes et les préréglages sont conservés (ils sont enregistrés par Home Assistant).

---

## Mise en route pas à pas

Ordre conseillé :

1. **Fraction chaudière** (si tu as une chaudière et une clim réversible) : créer l'entrée, puis vérifier les deux fractions et les deux températures qu'elle expose.
2. **Zones** : créer une zone par pièce. Dans *Configurer*, renseigner la fraction et la saison (*Sondes, type et cycle*) et, si tu as des vannes, l'onglet *Vannes thermostatiques*.
3. **Gestion chaudière** : choisir les relais, la sonde d'eau et les sources (les capteurs « Puissance chaudière » des zones).
4. **Gestion clim** : choisir le `climate` et les sources (les capteurs « Puissance de chauffe » des zones).
5. **Active « Simulation »** sur la chaudière et la clim. Observe pendant un moment les capteurs de statut et les seuils : rien n'est envoyé aux appareils.
6. Désactive tes anciennes automatisations qui pilotent les mêmes appareils, puis **désactive la simulation**.

---

## Les quatre types d'entrées

Chaque type s'ajoute depuis *Ajouter une intégration → Super Thermostat*. Les réglages avancés sont dans **Configurer** de chaque entrée (une explication est affichée sous chaque champ).

### 1. Zone

**À la création**

| Champ | Rôle |
|---|---|
| Nom | Nom de la zone. |
| Sonde de température intérieure | N'importe quelle entité numérique : `sensor`, `input_number`, `number`, ou une entité `weather` / `climate` (température lue dans ses attributs). |
| Sonde de température extérieure | Facultatif, mêmes types d'entités. Sans elle, la zone raisonne sans anticipation météo. |
| Type de zone | **Chauffage** (chaudière), **Climatisation**, ou **Chauffage + froid** (Auto, deux consignes). |
| Durée du cycle | Période de recalcul du pourcentage (5 à 240 min). Sert aussi de fenêtre de mesure pour l'apprentissage : 30 à 60 min conviennent. |

**Configurer → Sondes, type et cycle** : les champs ci-dessus, plus

| Champ | Rôle |
|---|---|
| Fraction chaudière | Entité 0-100 % (au choix : fraction « moyenne de la veille » ou « température actuelle » de l'entrée Fraction chaudière, ou toute autre entité). Puissance chaudière = puissance de chauffe × fraction. Vide = 100 %. |
| Entité « saison » | `input_boolean` / `switch` / `binary_sensor` : ON = été = froid. Sert au mode Auto. |
| Âge max de la sonde | Sans nouveau rapport valide de la sonde pendant ce délai : statut « défaillance sonde ». Une coupure brève (état « indisponible ») est tolérée tant que le dernier rapport valide a moins que ce délai. À régler un peu au-dessus du plus long intervalle entre deux rapports de ta sonde. |
| Puissance en cas de défaillance | Puissance demandée si la sonde est absente (0 par défaut). |

**Configurer → Vannes thermostatiques** : voir [Vannes thermostatiques](#vannes-thermostatiques).

**Configurer → Poêle à bois** : voir [Poêle à bois](#poêle-à-bois).

**Configurer → Régulation**

| Champ | Rôle |
|---|---|
| Puissance minimale | Sous ce pourcentage, la zone ne demande rien (5 % par défaut). |
| Limiter les cycles marche/arrêt | Une fois en chauffe, la zone ne s'arrête que sous 1 % au lieu de la puissance minimale. |
| Auto-apprentissage | La zone ajuste seule ses coefficients. À désactiver pour les figer. |
| Seuil « cycle précédent chaud » et Réduction après un cycle chaud | Compensent l'inertie d'un radiateur encore chaud : le cycle suivant est réduit. 0 = désactivé. |
| Marge de détection de défaillance | Si la zone chauffe (ou refroidit) mais que la température reste à plus de cette marge de la consigne et continue de s'en éloigner, 2 cycles de suite : statut « défaillance chauffage / clim ». |

**Configurer → Fenêtres** : capteurs d'ouverture, délai avant suspension (2 min) et délai avant reprise (2 min).

**Configurer → Notifications de défaillance** : voir [Notifications](#notifications-de-défaillance).

**Entités créées**

| Entité | Description |
|---|---|
| `climate.<zone>` | Modes `off`, `heat`, `cool`, `heat_cool` (selon le type), consigne(s), préréglages `none`, `home`, `sleep`, `away`. |
| Puissance de chauffe | Pourcentage total demandé en chauffe. |
| Puissance chaudière | Puissance de chauffe × fraction (attribut `fraction`). |
| Puissance de froid | Pourcentage demandé en froid (zones avec froid). |
| Statut | `heating`, `cooling`, `idle`, `off`, `suspended` (fenêtre), `stove` (poêle à bois : zone en pause), `sensor_failure`, `actuator_failure`. |
| Défaillance | Binaire, ON si panne de sonde ou de chauffage. |
| Poêle à bois : anticipation | Binaire (si un poêle est renseigné), ON quand le poêle est allumé et la pièce reste sous le seuil depuis le délai réglé. |
| Vanne qui ne suit pas | Binaire (si les positions réelles des vannes sont renseignées), ON si une vanne reste à plus de 10 % de sa consigne pendant le délai réglé. |
| `number` (configuration) | Coefficients appris, offsets, delta consigne, consignes des préréglages. |
| Bouton « Réinitialiser l'apprentissage » | Repart des coefficients par défaut. |

**Deux consignes et sens actif**

- Mode **Chauffage** ou **Froid** : le sens est forcé.
- Mode **Auto** (`heat_cool`) :
  - avec une entité « saison » : ON = froid, OFF = chauffe ;
  - sans : sous la consigne de chauffe, la zone chauffe ; au-dessus de la consigne de froid, elle refroidit ; entre les deux (zone morte), elle garde le sens précédent.
- La consigne de chauffe ne dépasse jamais celle de froid : si tu pousses l'une au-delà de l'autre, l'autre suit.
- **Consigne de froid à 35 °C = clim coupée.**

#### Vannes thermostatiques

Dans **Configurer → Vannes thermostatiques**, une zone peut piloter les vannes de ses radiateurs (entités `number` d'ouverture, par exemple `…_valve_setpoint`).

| Champ | Rôle |
|---|---|
| Vannes | Les entités d'ouverture à piloter (plusieurs radiateurs d'une même pièce se pilotent ensemble). |
| Position réelle des vannes | Facultatif : un capteur par vanne (par exemple `…_valve_position`), **dans le même ordre que les vannes**. Sert à comparer la position réelle à la consigne envoyée. |
| Alerte « vanne qui ne suit pas » après | Durée en minutes (30 par défaut, 0 = pas d'alerte). L'écart déclenchant est fixe : plus de **10 %** entre la consigne et la position réelle. |
| Demande suivie | **Champ libre** : n'importe quelle entité 0-100 % dont la valeur pilote l'ouverture (« Puissance chaudière » ou « Puissance de chauffe » de la zone, une fraction chaudière, une entité à toi…). **Vide = la puissance chaudière de la zone** (recommandé : c'est la part de chaleur que fournissent les radiateurs). |
| Ouverture proportionnelle | **Activée** : l'ouverture suit la demande dans la plage minimale – maximale. **Désactivée** : la vanne s'ouvre à l'ouverture fixe dès que la zone demande de la chaleur (le thermostat de la zone règle déjà la puissance, la vanne n'a plus qu'à laisser passer l'eau). |
| Ouverture minimale (à 1 % de demande) | Par exemple 15 %. C'est aussi l'ouverture à demande nulle avec « Ne jamais fermer complètement ». |
| Ouverture maximale (à 100 % de demande) | Par exemple 70 %. Entre les deux, l'ouverture varie linéairement. Mode proportionnel seulement. |
| Ouverture fixe (sans proportionnel) | Mode non proportionnel : ouverture dès qu'il y a de la demande. **Vide = 100 %.** |
| Écart minimal avant de changer l'ouverture | La vanne n'est modifiée que si l'ouverture voulue diffère d'au moins ce pourcentage de l'ouverture actuelle (5 % par défaut). La fermeture complète est toujours appliquée. |
| Ne jamais fermer complètement | Quand la demande est à 0, la vanne passe à l'ouverture minimale au lieu de se fermer. Prioritaire sur « Garder ouvert ». |
| Garder ouvert tant qu'aucune autre zone ne demande | Voir ci-dessous (activé par défaut). |
| Délai avant de renvoyer un ordre à une vanne | 30 minutes par défaut. Voir [Vérification et renvoi des ordres](#vérification-et-renvoi-des-ordres). |

**Ouverture proportionnelle activée.** La demande est ramenée à la plage réglée : avec 15 % à 1 % et 70 % à 100 %, une demande de 1 % ouvre à 15 %, 50 % à environ 43 %, 100 % à 70 %. Mettre 0 et 100 aux deux extrémités fait suivre la valeur de l'entité telle quelle. Si l'entité choisie est indisponible, rien n'est envoyé.

**Ouverture proportionnelle désactivée.** Dès que la demande est positive, la vanne s'ouvre à l'ouverture fixe (100 % si le champ est vide) : c'est la zone qui règle la puissance, pas la vanne.

**Quand la demande tombe à 0**, dans cet ordre de priorité (valable dans les deux modes) :
1. *Ne jamais fermer complètement* activé : la vanne passe à l'ouverture minimale.
2. Sinon, avec *Garder ouvert* (par défaut) : la vanne reste à son ouverture actuelle tant qu'aucune autre zone ne demande de chaudière, car circulateur et brûleur sont alors à l'arrêt et fermer pour rouvrir plus tard ne sert à rien. Dès qu'une autre zone demande de la chaudière, la vanne se ferme.
3. Sinon : fermeture immédiate.

Dans tous les cas : rien n'est envoyé en froid, en été (entité « saison » ON), ni quand l'écart avec l'ouverture actuelle est inférieur à l'écart minimal, ce qui épargne les piles. Les vannes sont recalculées à chaque cycle de la zone, à chaque changement de demande d'une zone et à chaque changement de l'entité suivie. Le capteur **Ouverture des vannes** de la zone affiche l'ouverture voulue, avec en attributs la source, le mode proportionnel ou non, la demande des autres zones, l'état des vannes et, si les positions réelles sont renseignées, la consigne, la position et l'écart de chaque vanne.

#### Vérification et renvoi des ordres

Les vannes sont vérifiées **toutes les minutes**, y compris quand le thermostat est éteint ou à 0 % de demande : si une vanne n'a pas la valeur voulue, l'ordre est envoyé (ou renvoyé).

Certaines vannes sur pile mettent **jusqu'à environ 30 minutes** entre l'ordre et le changement d'état. Pour ne pas les harceler :
- un ordre **différent** est envoyé tout de suite ;
- le **même** ordre n'est pas renvoyé avant le *délai avant de renvoyer un ordre* (30 min) ; passé ce délai, si la vanne n'a toujours pas suivi, il est renvoyé, et ainsi de suite ;
- dès que la vanne est à la bonne valeur (ou à moins que l'écart minimal), il n'y a plus rien à envoyer.

**Suivi de la position réelle.** Si tu renseignes les positions réelles, l'intégration compare pour chaque vanne la position à la consigne envoyée. Quand l'écart dépasse 10 % pendant plus que le délai réglé, l'indicateur **Vanne qui ne suit pas** de la zone s'active (attribut `valves_in_alert` : les vannes concernées, avec position, consigne et écart) et un avertissement est écrit dans les journaux. Le délai repart de zéro à chaque nouvel ordre, et rien n'est évalué en froid, en été, ni quand la position est indisponible. L'indicateur est séparé de « Défaillance » (régulation) : branche une automatisation dessus pour être notifié (pile faible, vanne bloquée…). La position réelle n'est qu'un témoin : l'intégration continue de comparer l'ouverture voulue à la consigne de la vanne, pour ne pas renvoyer un ordre qu'une vanne ne peut pas suivre.

> Les zones configurées avec l'ancien pilotage des vannes (proportionnel, fraction ou entité personnalisée) sont **migrées automatiquement** au démarrage vers ce champ libre, en conservant leur comportement.

> Conseils : pour une vanne sans pièce dédiée, rattache-la à la zone voisine ou crée une zone avec la température de la vanne comme sonde (les sondes intégrées aux vannes mesurent souvent trop chaud près du radiateur). Si la pompe est à vitesse fixe, garder un by-pass hydraulique quand presque toutes les vannes sont fermées.

**Préréglages** : `home` (Jour), `sleep` (Nuit), `away` (Parti). Ils portent les noms standards de Home Assistant, donc la tuile « préréglages » affiche leurs icônes. Chacun a une consigne de chauffe et une de froid, réglables dans les entités `number` de la zone.

**Réglages manuels**

- **Delta consigne** (0 par défaut = désactivé) : écart de lissage autour de la consigne, valable pour la chauffe et le froid. Avec 1 °C, la zone ne commence à chauffer que si le besoin existe à consigne − 0,5 °C, et vise alors consigne + 0,5 °C. Utile pour limiter les allers-retours sur une pièce qui oscille ; l'effet est modeste quand la température extérieure est basse.
- **Offset chauffe / froid** : pourcentage ajouté à la puissance calculée (0 par défaut), pour compenser une pièce structurellement trop froide ou trop chaude.
- Ces réglages **ne changent jamais seuls** (contrairement aux coefficients, qui sont appris) et s'appliquent immédiatement.

#### Poêle à bois

Dans **Configurer → Poêle à bois**, tu choisis un interrupteur (`input_boolean`, `switch`…) qui indique que le poêle est allumé.

| Champ | Rôle |
|---|---|
| Poêle à bois allumé (interrupteur) | Facultatif. Activé = le poêle chauffe la pièce. |
| Seuil d'anticipation | Température de la pièce sous laquelle on anticipe (21 °C par défaut). |
| Durée sous le seuil avant d'anticiper | 10 minutes par défaut. |

**Poêle allumé.** La zone passe en **pause** (statut `stove`) : elle ne demande plus rien, son mode, son préréglage et ses coefficients appris sont conservés, et le cycle interrompu n'est pas pris en compte pour l'apprentissage. Les vannes se ferment à **0 %, sans aucune contrainte** (« ne jamais fermer » et « garder ouvert » sont ignorés). Pendant la pause, la sonde n'est pas surveillée.

**Pièce qui se refroidit.** Si la température reste sous le seuil pendant la durée réglée, l'indicateur **Poêle à bois : anticipation** s'active et les vannes s'ouvrent déjà (ouverture maximale en mode proportionnel, ouverture fixe sinon), **sans relancer le thermostat**. Si la température remonte au-dessus du seuil, elles se referment.

**Poêle éteint** (l'interrupteur repasse à OFF) : la zone **reprend toute seule**, avec son mode et son préréglage d'avant. Il n'y a rien à remettre.

L'intégration ne pose pas de question sur ton téléphone : branche une automatisation sur l'indicateur d'anticipation, par exemple pour demander « Le poêle est-il éteint ? » et remettre l'interrupteur à OFF si oui (voir l'exemple plus bas).

#### Notifications de défaillance

Dans **Configurer → Notifications de défaillance** (zones et gestion chaudière) :

| Champ | Rôle |
|---|---|
| Service de notification | La liste propose les services existants (par exemple `notify.mobile_app_telephone`) ; tu peux aussi saisir le nom. Vide = aucune notification. |
| Message en cas de défaillance | Texte libre. Variables : `$nom` (nom de l'entrée) et `$cause` (cause). Vide = `$nom : $cause`. |

Une notification part **une fois** à chaque nouvelle défaillance, quand elle dure depuis plus de 5 minutes (pour éviter les faux messages au démarrage), avec le nom de l'entrée en titre. Elle repart si la défaillance disparaît puis revient. Défaillances surveillées : *zone* : sonde de température absente ou périmée, chauffage qui ne chauffe pas, vanne qui ne suit pas ; *chaudière* : sonde d'eau absente ou périmée, coupure de sécurité.

### 2. Fraction chaudière

Remplace un capteur `template` « fraction chaudière ». À partir d'**une seule entité de température**, l'entrée calcule en permanence deux fractions et expose les deux températures :

| Entité | Description |
|---|---|
| **Fraction chaudière (moyenne de la veille)** | Fraction calculée sur la **moyenne de la veille** (historique de l'entité). Valeur stable toute la journée, mise à jour à 00:05. |
| **Fraction chaudière (température actuelle)** | Fraction calculée sur la **température actuelle**, en temps réel. |
| **Température moyenne de la veille** | Attributs `source` (`history`, `cache` ou `fallback`) et `as_of`. |
| **Température actuelle** | Valeur lue sur l'entité source. |

Chaque zone, la gestion clim ou une vanne choisit **laquelle des deux fractions suivre** : il n'y a donc plus de mode à régler.

| Champ | Rôle |
|---|---|
| Entité de température | Une entité numérique (ou `weather` / `climate`, sans moyenne de la veille dans ce cas). |
| Température de repli | Utilisée pour une température introuvable (10 °C). |
| Seuil haut | Au-dessus : 0 % de chaudière (9 °C). |
| Seuil bas | En dessous : 100 % de chaudière (−3 °C). |
| Fraction minimale d'utilisation | Sous ce pourcentage, la fraction passe à 0 % : les radiateurs seraient trop peu ouverts pour que la chaudière serve (15 %). |

Entre les deux seuils, la fraction varie linéairement. Les deux fractions ont les attributs `raw_fraction` (avant seuil minimal), `min_fraction` et `source`.

> La moyenne de la veille lit l'historique du recorder (valeurs numériques de l'entité). Si la lecture échoue, la dernière valeur connue est utilisée, puis la température de repli.

### 3. Gestion chaudière

Une seule entrée.

| Champ | Rôle |
|---|---|
| Relais du brûleur, relais du circulateur | `switch` ou `input_boolean`. |
| Sonde de température d'eau | Température de la chaudière. |
| Sources de puissance | Entités numériques additionnées et plafonnées à 100 % : en général les capteurs « Puissance chaudière » des zones. Tu peux en ajouter d'autres à la main. |

**Configurer → Temporisations et sécurité** : post-circulation du circulateur (0 min), durée mini brûleur allumé (2 min) et éteint (2 min), température de sécurité (85 °C), âge max de la sonde d'eau (10 min).

**Configurer → Notifications de défaillance** : service de notification et message (voir [Notifications](#notifications-de-défaillance)) pour la sonde d'eau absente et la coupure de sécurité.

**Entités** : Demande totale, Seuil bas eau, Seuil haut eau, Statut (`disabled`, `idle`, `circulating`, `heating`, `water_sensor_failure`, `safety_cutoff`), Brûleur, Circulateur, interrupteurs **Gestion active** et **Simulation**, et trois réglages :

- **Température d'eau à 1 %** (20 °C), **à 100 %** (72 °C) et **décalage seuil bas / haut** (5 °C).

### 4. Gestion clim

Remplace une automatisation qui allume, règle et éteint une clim réversible.

| Champ | Rôle |
|---|---|
| Clim | L'entité `climate`. |
| Sources de puissance de chauffe | En général les capteurs « Puissance de chauffe » (totale) des zones. |
| Sources de puissance de froid | Facultatif : les capteurs « Puissance de froid ». Sans elles, la gestion ne s'occupe que de la chauffe. |
| Fraction chaudière | Facultatif : sert d'interrupteur (voir plus bas). |
| Entité « saison » | Facultatif : ON = froid, OFF = chauffe. |

**Configurer → Temporisations** : délai avant allumage (10 min), intervalle de réglage de la consigne (5 min), durée mini d'allumage (5 min), pause entre le mode et la consigne (20 s).

**Entités** : Demande, Consigne envoyée à la clim, Statut (`disabled`, `idle`, `heating`, `cooling`, `fraction_cutoff`, `summer_season`), interrupteurs **Gestion active** et **Simulation**, et les réglages :

- décalage de la consigne de chauffe à 0 % (−1 °C) et à 100 % (+3 °C) ;
- décalage de la consigne de froid à 0 % (+1 °C) et à 100 % (−3 °C) ;
- **seuil de coupure** sur la fraction (100 %).

---

## Comment ça calcule

### Zone

À chaque cycle :

```
puissance % = sens × (consigne − T intérieure) × coeff_int
            + sens × (consigne − T extérieure) × coeff_ext
            + offset
```

bornée entre 0 et 100. Le premier terme corrige l'écart ; le second **anticipe** les déperditions grâce à la température extérieure.

- **Auto-apprentissage** : à la fin d'un cycle, la zone compare la montée en température obtenue à celle attendue et corrige ses coefficients par moyenne pondérée (le poids monte jusqu'à 50 : « 50 = apprentissage terminé »). Quatre coefficients : chauffe et froid, intérieur et extérieur. Une mesure aberrante ne peut pas déplacer un coefficient de plus d'un facteur 3.
- L'apprentissage est sauté quand le cycle précédent a été interrompu (zone arrêtée, fenêtre ouverte, panne de sonde) ou quand la puissance était nulle ou saturée.
- **Défaillance du chauffage** : détectée seulement quand l'apprentissage est mûr (compteur au-dessus de 25), après deux cycles de suite.
- Un coefficient réglé à la main ré-initialise son compteur à 10.
- Le pourcentage est **constant pendant tout le cycle** : une zone ne commute rien.
- **La température affichée par l'entité `climate` est celle de la sonde, en direct** (mise à jour à chaque changement de la sonde). C'est le **calcul du pourcentage** qui lit la température une fois par cycle, au début de chaque cycle : c'est ce qui rend la régulation stable (durée du cycle réglable). L'attribut `sensor_entity` de l'entité `climate` indique la sonde réellement utilisée, `sensor_age_minutes` l'âge de son dernier rapport.
- **Fraîcheur de la sonde** : vérifiée **chaque minute**. Elle repose sur le dernier rapport valide de la sonde (le plus récent entre `last_updated` et `last_reported`). Une défaillance apparaît seulement quand ce rapport a plus que l'*âge max de la sonde*, et disparaît dès qu'un nouveau rapport arrive, sans attendre la fin du cycle. La notification n'est envoyée que si elle dure plus de 5 minutes.

### Chaudière

- Demande = somme des sources, plafonnée à 100 %.
- Le circulateur s'allume dès que la demande est positive (et reste allumé la durée de post-circulation).
- Le seuil bas d'eau varie linéairement de la température à 1 % jusqu'à (température à 100 % − décalage) ; le seuil haut = seuil bas + décalage. Avec 20 °C, 72 °C et 5 °C : à 1 %, 20 à 25 °C ; à 100 %, 67 à 72 °C.
- Le brûleur s'allume sous le seuil bas, s'éteint au-dessus du seuil haut et ne change pas entre les deux. Il s'éteint immédiatement s'il n'y a plus de demande, si la sonde d'eau est muette ou si la température de sécurité est atteinte.

### Clim

- Consigne = température mesurée par la clim + décalage, arrondie à l'entier. Le décalage varie linéairement avec la demande.
- Allumage seulement si le délai depuis le dernier réglage est écoulé ; la consigne n'est renvoyée que si elle diffère de celle de la clim, au plus toutes les 5 min.
- **Fraction** : elle n'agit que comme interrupteur. Sous le seuil de coupure, la clim suit la puissance totale (sans être réduite par la fraction). Au seuil ou au-dessus, elle s'arrête immédiatement.
- Entre la fraction minimale et le seuil de coupure, la chaudière et la clim chauffent donc ensemble.

---

## Exemples

### Tuile avec les préréglages

```yaml
type: tile
entity: climate.sejour
vertical: false
features:
  - style: icons
    type: climate-preset-modes
    preset_modes:
      - none
      - home
      - sleep
      - away
features_position: inline
```

### Choisir le préréglage depuis une automatisation

```yaml
alias: Préréglage selon le mode de la maison
triggers:
  - trigger: state
    entity_id: input_select.mode_maison
actions:
  - action: climate.set_preset_mode
    target:
      entity_id: climate.sejour
    data:
      preset_mode: >-
        {{ {'Jour': 'home', 'Nuit': 'sleep', 'Parti': 'away'}[trigger.to_state.state] }}
mode: single
```

### Poêle à bois : demander confirmation sur le téléphone

À utiliser avec l'indicateur « Poêle à bois : anticipation » de la zone (la pause de la zone et les vannes sont gérées par l'intégration) :

```yaml
alias: Poêle à bois - confirmation
description: Quand la pièce se refroidit poêle allumé, demande si le poêle est éteint.
triggers:
  - trigger: state
    entity_id: binary_sensor.sejour_poele_a_bois_anticipation
    to: "on"
actions:
  - action: notify.mobile_app_telephone
    data:
      title: Poêle à bois
      message: Le poêle n'est plus alimenté ?
      data:
        actions:
          - action: POELE_ETEINT
            title: Oui éteint
          - action: POELE_REPART
            title: Il repart !
  - wait_for_trigger:
      - trigger: event
        event_type: mobile_app_notification_action
        event_data:
          action: POELE_ETEINT
      - trigger: event
        event_type: mobile_app_notification_action
        event_data:
          action: POELE_REPART
    timeout: "01:00:00"
    continue_on_timeout: false
  - if:
      - condition: template
        value_template: "{{ wait.trigger.event.data.action == 'POELE_ETEINT' }}"
    then:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.poele_bois
mode: restart
```

### Fixer deux consignes

```yaml
action: climate.set_temperature
target:
  entity_id: climate.sejour
data:
  target_temp_low: 21
  target_temp_high: 24
```

---

## Dépannage

### La clim ne démarre pas

Ouvrir les attributs du capteur **Statut** de la gestion clim (Outils de développement → États). L'attribut `reason` dit ce qui se passe, le même texte est écrit dans les journaux à chaque changement :

| `reason` | Signification |
|---|---|
| `disabled` | L'interrupteur « Gestion active » est éteint. |
| `summer_entity_on` | L'entité « saison » est ON et aucune source de froid n'est renseignée : la gestion ne touche à rien. |
| `climate_unavailable` | L'entité `climate` est indisponible. |
| `fraction_cutoff` | La fraction a atteint le seuil de coupure. |
| `no_demand` | Les sources donnent 0 % (vérifier que ce sont bien les capteurs de puissance des zones). |
| `waiting_start_delay` | Une demande existe, mais le délai depuis le dernier réglage n'est pas écoulé. |
| `regulating` | La clim est dans le bon mode, la consigne est ajustée. |
| `dry_run_would_act` | Simulation active : voir `pending_actions`. |
| `acting` | Des commandes viennent d'être envoyées. |

Les attributs `sources`, `fraction`, `climate_mode`, `setpoint_computed` et `seconds_since_last_change` complètent le diagnostic.

### Autres cas courants

| Symptôme | Piste |
|---|---|
| La température de l'entité `climate` ne correspond pas à la sonde que je regarde | Regarde l'attribut `sensor_entity` de l'entité `climate` (Outils de développement → États) : c'est la sonde réellement utilisée par la zone. Elle peut différer de celle que tu consultes. |
| La zone reste en statut `stove` | L'interrupteur « poêle à bois allumé » est encore ON. |
| La zone reste « Au repos » | Mode Auto sans entité saison, température dans la zone morte entre les deux consignes. |
| « Défaillance sonde » ou notification de sonde périmée | Le dernier rapport valide de la sonde a plus que « Âge max de la sonde » (attribut `sensor_age_minutes` de l'entité `climate`). Règle ce délai au-dessus du plus long intervalle entre deux rapports de ta sonde. Pour la sonde d'eau de la chaudière, le réglage équivalent est « Âge max de la sonde d'eau » (10 min par défaut). |
| Les coefficients ne bougent pas | Auto-apprentissage désactivé, ou puissance toujours nulle ou saturée à 100 %. |
| Fraction à 0 % alors qu'il fait froid | Fraction minimale non atteinte, ou température absente : voir `raw_fraction` et `source` des fractions, et « Température moyenne de la veille ». |
| La chaudière ne s'allume pas | Vérifier le capteur Statut de la chaudière (`water_sensor_failure`, `safety_cutoff`) et que « Simulation » est éteint. |
| Une vanne ne se ferme pas | L'ordre est renvoyé toutes les 30 minutes tant que la vanne n'a pas suivi (délai réglable) ; voir « Vanne qui ne suit pas » si tu as renseigné sa position. |
| Anciennes entités « non disponibles » après une mise à jour | Supprimer les entités orphelines dans Paramètres → Entités. |

---

## Sécurité et limites

- **Prévoir un arrêt local sur les relais** (minuterie auto-off, par exemple) : si Home Assistant ne répond plus, les relais gardent leur dernier état.
- **La simulation** est là pour valider les seuils avant le premier vrai démarrage.
- **Quotas d'API** : si la clim passe par un service cloud avec un nombre de commandes par jour limité, les délais par défaut (réglage toutes les 5 min, allumage 10 min) peuvent ne pas suffire en théorie. Passer l'intervalle de réglage à 10 min plafonne à 144 réglages par jour.
- Pas de planning intégré : utiliser des automatisations pour changer de préréglage.
- Une seule gestion chaudière par installation.
- La température est lue en °C (conversion automatique si l'entité est en °F).

---

## Historique des versions

| Version | Changements |
|---|---|
| 1.0.3 | **Retour de la gestion du poêle à bois** (retirée par erreur en 1.0.2) : onglet *Poêle à bois*, zone en pause, vannes à 0 %, anticipation, indicateur et statut `stove`. Si les réglages du poêle ont été supprimés par la 1.0.2 au démarrage, il faut les ressaisir. |
| 1.0.2 | Retrait de la gestion du poêle à bois (onglet, indicateur d'anticipation, statut `stove`) ; les anciens réglages sont supprimés automatiquement au démarrage. |
| 1.0.1 | Sonde de la zone : coupures brèves tolérées, défaillance détectée et levée chaque minute (plus de défaillance « collée » jusqu'à la fin du cycle), attributs `sensor_entity` / `sensor_age_minutes` sur l'entité `climate`. |
| 1.0.0 | **Vannes vérifiées chaque minute** avec renvoi des ordres non suivis après un délai (30 min par défaut) ; **notifications de défaillance** (service + message) pour les zones et la chaudière. |
| 0.10.0 | Vannes : interrupteur « ouverture proportionnelle » (désactivé = ouverture fixe, 100 % par défaut) ; ancienne configuration migrée automatiquement. Nettoyage : une seule marge de détection de défaillance, suppression des réglages de bascule devenus inutiles, schéma du README. |
| 0.9.0 | Vannes : position réelle (capteur par vanne), affichage consigne / position / écart, indicateur « Vanne qui ne suit pas » (écart fixe de 10 %, délai réglable). |
| 0.8.0 | Vannes : un champ libre « demande suivie » remplace les listes « pilotage » et « demande suivie », interrupteur « ne jamais fermer complètement » (ouverture minimale). |
| 0.7.1 | Explications ajoutées sous les champs qui n'en avaient pas. |
| 0.7.0 | Onglet « Vannes thermostatiques » dans les options des zones ; ouverture proportionnelle à la demande (plage réglable), écart minimal, vannes gardées ouvertes tant qu'aucune autre zone ne demande ; capteur « Ouverture des vannes ». |
| 0.6.0 | Fraction chaudière : fractions « température actuelle » et « moyenne de la veille » (plus de mode à choisir) et leurs deux températures ; vannes : trois modes (demande, fraction, personnalisé) ; préréglages fixes (Vacances retiré) ; lien du bouton « ? » vers le dépôt. |
| 0.5.1 | Retrait de l'étape « Préréglages » (trois préréglages fixes), les réglages manuels s'appliquent immédiatement. |
| 0.5.0 | Préréglages `home` / `sleep` / `away` avec icônes, explications sous chaque champ, fraction minimale, vannes thermostatiques dans les zones. |
| 0.4.0 | Zone à deux consignes, préréglages à deux consignes, sens actif par saison, froid dans la gestion clim. |
| 0.3.x | Gestion clim (chauffe), seuil de coupure sur la fraction, diagnostics. |
| 0.2.0 | Fraction chaudière, mode simulation, capteurs de température libres. |
| 0.1.0 | Zones, gestion chaudière. |

---

## Crédits et licence

La logique de régulation (cycle, anticipation extérieure, auto-apprentissage, détection de défaillance) est portée du plugin *Thermostat* de [Jeedom](https://www.jeedom.com), publié sous licence **GPLv3**. Ce portage doit donc être redistribué sous la même licence.
