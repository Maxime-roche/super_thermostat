# Super Thermostat v0.5.0 (HA 2026.10)

Installation : copier `custom_components/super_thermostat/` dans `/config/custom_components/`, redémarrer HA,
puis Paramètres → Appareils et services → Ajouter une intégration → « Super Thermostat ».

1. **Zone** : une seule zone par pièce, avec **deux consignes** (chauffe et froid ; l'écart entre les deux est une zone morte).
   Mode Auto (`heat_cool`) : le sens suit l'entité « saison » si elle est configurée (ON = été = froid),
   sinon la température (sous la consigne de chauffe : chauffe ; au-dessus de la consigne de froid : froid).
   Préréglages (Configurer → Préréglages, par défaut home / sleep / away = Jour / Nuit / Parti, avec les icônes standards de la tuile) :
   chacun a une consigne de chauffe et une de froid, réglables dans les entités de la zone ; froid à 35 °C = clim coupée.
   Vannes thermostatiques (Configurer → Sondes, type et cycle) : la zone y écrit l'ouverture (%) = fraction chaudière, en hiver seulement.
   Sorties : `climate`, « Puissance de chauffe », « Puissance chaudière » (= chauffe × fraction), « Puissance de froid ».
2. **Gestion chaudière** (une seule) : relais brûleur/circulateur, sonde d'eau, sources = « Puissance chaudière ».
3. **Fraction chaudière** : référence (valeur ou moyenne de la veille) → 0-100 % de chaudière ; seuils dans « Configurer ».
   Fraction minimale (15 % par défaut) : en dessous, la fraction passe à 0 % (radiateurs trop peu ouverts).
4. **Gestion clim** : sources de chauffe = « Puissance de chauffe », sources de froid facultatives = « Puissance de froid ».
   Chauffe : consigne = round(T Daikin + décalage), -1 °C (0 %) → +3 °C (100 %), coupée quand la fraction atteint le seuil.
   Froid : décalage +1 °C (0 %) → -3 °C (100 %), réglable. Entité « saison été » : ON = froid, OFF = chauffe.
   Interrupteur « Simulation » (chaudière et clim) : tout est calculé, rien n'est envoyé aux appareils.

Sécurité : prévoir un arrêt local sur les relais (ex. minuterie auto-off Shelly) au cas où HA ne répondrait plus.
