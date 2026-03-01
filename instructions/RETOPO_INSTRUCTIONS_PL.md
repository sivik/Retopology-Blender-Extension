# Retopo Stroke Tool  — Instrukcja użytkownika

---

## Szybki start

1. Załaduj high-poly model do sceny
2. W panelu **Retopo Tool** (N-Panel → zakładka "Retopo Tool") wskaż go w polu **High-Poly**
3. Wybierz **Metodę Retopo** i **Preset gęstości**
4. Kliknij **▶ URUCHOM RETOPO**

Wynik pojawi się jako nowy obiekt `Retopo_NazwaModelu_TRYB`.

---

## Tryby retopologii

### 1. Voxel Remesh

Najszybszy tryb. Dzieli przestrzeń na siatkę sześcianów (vokseli) i buduje z nich mesh.
Topologia jest całkowicie nowa — nie ma związku z oryginalną siatką.

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Voxel Size** | Rozmiar voksela — mniejszy = więcej polygonów | 0.03–0.05 dla postaci, 0.01–0.02 dla detali |
| **Adaptivity** | Trianguluje płaskie obszary, zmniejsza poly w nudnych miejscach | Ustaw 0.1–0.3 dla modeli architektonicznych. Uwaga: wyłącza „Fix Poles" |

**Wynik:** Czysta siatka quadów, równomiernie rozłożona po całej powierzchni.
**Ograniczenie:** Nie szanuje granicy otwartych siatek. Wymagany zamknięty mesh (manifold).

---

### 2. Remesh + Shrinkwrap

Działa jak Voxel, ale po remeshu nakłada **Shrinkwrap modifier** — siatka jest „naciągana" z powrotem na oryginalny kształt. Efekt: znacznie lepsze dopasowanie do detali high-poly.

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Voxel Size** | Rozmiar voksela pierwszego remeshu | Możesz użyć nieco większego niż w trybie Voxel — Shrinkwrap doprecyzuje kształt |
| **Shrinkwrap Offset** | Odstęp od powierzchni targetu po naciągnięciu | Zostaw 0.0 dla maksymalnego dopasowania; zwiększ jeśli siatka „przebija" model |
| **Adaptivity** | Jak w trybie Voxel | j.w. |

**Wynik:** Lepiej dopasowana siatka niż czysty Voxel, nadal quad-dominant.
**Ograniczenie:** Wolniejszy. Na bardzo skomplikowanych kształtach Shrinkwrap może nie trafić w zagłębienia.

---

### 3. Decimate

Nie tworzy nowej topologii — **redukuje liczbę polygonów istniejącej siatki**, zachowując jej strukturę. Wierzchołki pozostają w tych samych miejscach co oryginał.

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Decimate Ratio** | Ułamek pozostałych face'ów (1.0 = brak zmian, 0.3 = 30% oryginału) | 0.3–0.5 dla LOD-ów, 0.1–0.2 dla bardzo agresywnej redukcji |

**Wynik:** Zachowana oryginalna topologia, szybko.
**Ograniczenie:** Nie poprawia jakości siatki — jeśli oryginał ma złą topologię (trójkąty, N-gony), wynik też ją będzie miał. Wynikowa siatka zawiera trójkąty.

---

### 4. Quadriflow

Najwyższa jakość topologii spośród wbudowanych narzędzi Blendera. Buduje **czystą siatkę quadów** z zachowaniem krzywizn powierzchni. Odpowiednik ZRemeshera dla Blendera — wolniejszy niż Voxel, ale znacznie lepszy wynik.

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Target Faces** | Docelowa liczba face'ów (przybliżona) | Quadriflow może nieznacznie odbiegać od celu |
| **Uwzględnij krzywiznę** | Zagęszcza siatkę w miejscach o dużej krzywiźnie (oczy, usta, stawy) | Włącz zawsze dla postaci organicznych |
| **Zachowaj Hard Edges** | Edge loopy wzdłuż ostrych krawędzi | Kluczowe dla hard-surface i mechanicznych obiektów |
| **Zachowaj Granice** | Wyrównuje siatkę do granicy otwartego mesha | Włącz gdy model jest otwarty (np. odcięty na połowie) |
| **Użyj Symetrii** | Remeshuje jedną połowę i mirroruje wynik | Włącz zawsze dla symetrycznych postaci/pojazdów — gwarantuje identyczną topologię po obu stronach |
| **Wygładź Normale** | Wygładza normale po remeshu | Opcjonalne; poprawia wygląd przed subdivision |

**Wynik:** Najczyściejsze quady z wbudowanych trybów, dobry edge flow.
**Ograniczenie:** Długi czas obliczeń przy dużej liczbie face'ów (>10k). Nie zawsze daje idealny edge flow — do tego służą stroke'i.

---

### 5. Instant Meshes

Korzysta z **zewnętrznego programu Instant Meshes** (open-source, do pobrania osobno). Specjalizuje się w generowaniu regularnych edge loopów. Na wielu modelach daje wyniki porównywalne z Quad Remesherem.

**Wymaganie:** Ścieżka do pliku wykonywalnego Instant Meshes (pole „Binarka").
Kliknij ikonę zakładki obok pola aby zapisać ścieżkę jako domyślną globalnie (Edit → Preferences → Add-ons → Retopo Stroke Tool).

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Target Faces** | Docelowa liczba face'ów | IM jest bardzo dokładny w trafianiu w cel |
| **Crease Angle** | Kąt (0–90°) powyżej którego krawędź to hard edge | 20–35° dla większości modeli; 10–15° dla bardzo detailowych hard-surface |
| **Smooth Iterations** | Iteracje wygładzania po remeshu (0–10) | 2–4 dla organicznych, 0–1 dla hard-surface (zachowanie krawędzi) |
| **Dominant Quads** | Pozwala na trójkąty przy polach (singularities) | Włącz gdy IM generuje artefakty — poprawia stabilność przy trudnej topologii |
| **Align to Boundaries** | Wyrównuje edge loopy do granicy otwartej siatki (`-b`) | Kluczowe przy retopo odciętych modeli: half-body, dłonie, elementy odzieży |
| **Deterministyczny** | Wolniejszy, ale zawsze daje identyczny wynik (`-d`) | Przydatne w pipeline produkcyjnym — ten sam model = ten sam wynik |
| **Wątki CPU** | Liczba rdzeni (0 = auto) | Zwiększ na maszynach wielordzeniowych dla przyspieszenia |

**Wynik:** Bardzo regularne edge loopy, świetny dla postaci i obiektów z powtarzalnymi formami.
**Ograniczenie:** Wymaga zewnętrznej binarki.

---

### 6. QuadWild

Korzysta z **QuadWild (Pietroni et al. 2021)** — open-source solvera najbliższego jakością ZRemesherowi. Używa globalnej parametryzacji i ILP do optymalnego rozmieszczenia singularności.

**Dwa sposoby uruchomienia:**

**Opcja A — addon QRemeshify (zalecana, bez potrzeby ręcznej binarki):**
Zainstaluj **QRemeshify** z [github.com/ksami/QRemeshify](https://github.com/ksami/QRemeshify). Gdy jest wykryty, panel pokazuje „QRemeshify zainstalowany — binarka bundlowana ✓" i wywołuje go automatycznie.

**Opcja B — ręczna binarka (fallback):**
Pobierz `quadwild-bimdf` z [github.com/nicopietroni/quadwild-bimdf](https://github.com/nicopietroni/quadwild-bimdf) i wpisz ścieżkę w polu „Binarka".

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Scale Factor** | Rozmiar quadów (tryb QRemeshify): < 1 = więcej detali, > 1 = mniej poly | Presety: GAME=2.5, MEDIUM=1.0, HIGH=0.4 |
| **Target Faces** | Docelowa liczba face'ów (tryb binarki) | Używane tylko gdy QRemeshify NIE jest zainstalowany |
| **Sharp Angle** | Kąt powyżej którego krawędź jest traktowana jako ostra | 25–35° dla standardowych modeli |

**Wynik:** Najlepsza automatyczna jakość quadów — regularny edge flow zbliżony do ZRemeshera.
**Ograniczenie:** Najwolniejszy tryb. Wymaga QRemeshify lub ręcznej binarki.

---

## Preset gęstości

Szybki sposób na dobór liczby polygonów bez ręcznego ustawiania parametrów.

| Preset | Zakres | Zastosowanie |
|---|---|---|
| **Game** | ~500–1000 face'ów | Real-time, mobile, background assets |
| **Medium** | ~1000–3000 face'ów | Standardowe assety do gier (główny bohater, pojazdy) |
| **High** | ~3000–6000 face'ów | Rendering, promo, cinematic |
| **Custom** | Dowolny | Pełna kontrola — ręczne suwaki |

---

## Edge Loops (Stroke Guidance)

Pozwala **ręcznie narysować linie na modelu**, które wpływają na kierunek topologii podczas remeshu.

### Rysowanie stroke'a

1. Kliknij **+ Narysuj Edge Loop**
2. **Przytrzymaj LMB** i prowadź kursor po powierzchni modelu
3. Puść LMB — stroke zapisuje się jako niebieska krzywa beziera

Stroke'i są widoczne w scenie jako obiekty typu Curve i można je zaznaczać / ukrywać z listy.

### Symetria

Włącz **Symetria** i wybierz oś (X / Y / Z) — każdy rysowany stroke automatycznie dostanie lustrzane odbicie po drugiej stronie. Lustrzane stroke'i są zielone.

### Guidance — tryby wpływu

Włącz **Użyj jako Guidance** aby stroke'i wpływały na remesh. Dostępne dwa tryby:

| Tryb | Działanie | Kiedy używać |
|---|---|---|
| **Snap** | Wierzchołki blisko stroke'a skaczą dokładnie NA jego linię → twarde edge loopy | Gdy chcesz wymusić konkretny edge loop w danym miejscu (np. wokół oka, linii ust) |
| **Field** | Kierunek krawędzi wyrównuje się z tangentą stroke'a bez skakania na niego → miękkie prowadzenie przepływu | Gdy chcesz wpłynąć na ogólny kierunek quadów w danej strefie bez twardych cięć |

**Snap — parametr:**
- **Snap Radius** — promień wpływu (im większy, tym więcej wierzchołków przyciągniętych do stroke'a). Quadratic falloff: pełna siła przy centrum, zero na granicy — bez twardych artefaktów.

**Field — parametry:**
- **Influence Radius** — strefa wpływu tangentowego pola stroke'a
- **Strength** — siła wyrównania (0 = brak efektu, 1 = maksymalne wyrównanie)

---

## Opcje zaawansowane

Niektóre opcje są widoczne tylko dla trybów, w których mają sens:

| Opcja | Dostępna dla |
|---|---|
| Mesh Healing | Wszystkie tryby |
| Curvature Pre-pass | Wszystkie oprócz Decimate |
| Hard Edge Pre-pass | Tylko Quadriflow i Instant Meshes |
| Smooth + Re-project | Wszystkie oprócz Decimate i Shrinkwrap |
| LOD Chain | Wszystkie tryby |
| Quality Metrics | Wszystkie tryby |

---

### Mesh Healing

Przed remeshem automatycznie naprawia siatkę targetu:
1. **Remove Doubles** — scala wierzchołki bliżej niż 0,1 mm
2. **Fill Holes** — wypełnia otwory w siatce (preferuje quady)
3. **Recalc Normals** — naprawia odwrócone normale

Panel informuje ile werteksów scalono i ile dziur zamknięto.

**Kiedy włączyć:** Domyślnie ON. Eliminuje główną przyczynę dziur po Voxel Remesh.

---

### Curvature Pre-pass *(niedostępne dla Decimate)*

Oblicza dwie miary krzywizny na targecie i maluje je jako Vertex Colors:

| Kanał | Formuła | Co wykrywa |
|---|---|---|
| `CurvatureDensity` | Krzywizna Gaussa `\|2π − Σθ\| / A` | Ostre rogi, wypukłości — czerwony = dużo, niebieski = płasko |
| `MeanCurvature` | Cotangent Laplacian `\|ΣwⱼΔvⱼ\| / 2A` | Zagięcia i siodła (kąciki ust, łuk brwiowy) — lepszy dla organiki |

Użyj przycisku **Bake Now** aby podejrzeć mapę krzywizny przed remeshem.

> **Uwaga:** Baked vertex colors są narzędziem **wizualizacji** — pomagają zdecydować gdzie postawić stroke'i. Quadriflow oblicza krzywiznę wewnętrznie (parametr `Uwzględnij krzywiznę`); żaden tryb nie czyta bezpośrednio tych vertex colors do sterowania gęstością.

**Kiedy używać:** Jako pomoc przy rysowaniu stroke'ów — narysuj je tam gdzie `CurvatureDensity` jest czerwona.

---

### Hard Edge Pre-pass *(tylko Quadriflow i Instant Meshes)*

Przed remeshem skanuje krawędzie targetu i oznacza jako **sharp + crease** te, których kąt dwuścienny przekracza próg.

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Crease Angle** | Kąt powyżej którego krawędź jest traktowana jako ostra | 30° dla standardowych modeli; 15° dla detailowych hard-surface |

Oznaczone krawędzie są szanowane przez:
- **Quadriflow** (parametr `Zachowaj Hard Edges`)
- **Instant Meshes** (parametr `Crease Angle`)

**Kiedy włączyć:** Przy każdym modelu zawierającym ostre przejścia formy — mechaniczne obiekty, pojazdy, architektura, elementy zbroi.

> **Uwaga dla Blendera 4.0+:** Warstwa crease w BMesh jest teraz atrybutem float (`crease_edge`). Addon obsługuje obie wersje automatycznie.

---

### Smooth + Re-project *(niedostępne dla Decimate i Shrinkwrap)*

Po remeshu uruchamia iteracyjną pętlę: **Cotangent Laplacian smooth → rzutowanie z powrotem na high-poly**. Wyrównuje rozkład wierzchołków i poprawia dopasowanie siatki do oryginału.

| Parametr | Opis | Wskazówka |
|---|---|---|
| **Iteracje** | Liczba cykli smooth → re-project | 3–5 dla standardowych modeli; 8–15 dla bardzo nierównomiernych siatek |
| **Smooth Factor** | Siła Laplacian smooth per iterację | 0.3–0.5 bezpieczne; >0.7 może zmienić kształt |

Używa **cotangent-weighted Laplacian** (nie uniformowego) — eliminuje skurcz geometrii (shrinkage bias) typowy dla uniform smooth na nieregularnych siatkach.

**Kiedy włączyć:** Gdy wynikowa siatka ma nierównomierne wierzchołki lub lekko odbiega od powierzchni targetu. Szczególnie przydatny po trybach Voxel, Quadriflow, Instant Meshes i QuadWild.
Shrinkwrap jest pominięty — ten tryb już wykonuje własne rzutowanie na powierzchnię.

---

### LOD Chain

Po remeshu automatycznie generuje **łańcuch LOD** przez progresywny Decimate w dedykowanej kolekcji.

| Poziomy LOD | Poly count |
|---|---|
| LOD0 | 100% (pełny wynik remeshu) |
| LOD1 | 50% |
| LOD2 | 25% |
| LOD3 | 10% |

Kolekcja `LOD_NazwaModelu` pojawia się w outlinerze.

**Kiedy włączyć:** Przy tworzeniu assetów do silników real-time (Unity, Unreal). Generuje komplet LOD-ów jednym kliknięciem.

---

### Quality Metrics

Po remeshu oblicza i wyświetla metryki jakości wynikowej siatki:

| Metryka | Cel | Znaczenie |
|---|---|---|
| **Quady %** | ≥ 95% ✅ | Procent face'ów które są quadami (4-kąty) |
| **Poles** | jak najmniej | Wierzchołki z valence ≠ 4 (nieregularne połączenia) |
| **Aspect ratio** | ~1.0 | Stosunek najdłuższej do najkrótszej krawędzi face'a — idealnie kwadratowe = 1.0 |
| **Kąt (Jacobian)** | ≥ 0.85 ✅ | min\|sin θ\| kątów wewnętrznych quada — wykrywa skrzywione i ściśnięte quady |
| **Dev. od HP** | ~0 mm | Średnia odległość wynikowej siatki od powierzchni high-poly |

---

## Tips & Tricks — który tryb kiedy

### Szybki prototyp / blokout
→ **Voxel Remesh** z Presetem Game lub Medium.
Cel: sprawdzić proporcje, nie topologię. Sekundy roboty.

### Finalna retopologia postaci organicznej
→ **Quadriflow** z włączoną Krzywizną i Symetrią + **Smooth + Re-project** (5 iteracji).
Opcjonalnie: narysuj stroke'i wokół oka, ust, uszu i włącz **Snap Guidance**.

### Hard-surface (mecha, zbroja, pojazd)
→ **Hard Edge Pre-pass** (30°) + **Quadriflow** lub **Instant Meshes**.
Quadriflow: włącz `Zachowaj Hard Edges`.
Instant Meshes: Crease Angle 20°, Smooth 1, Dominant Quads ON.

### Game asset z kompletnym LOD
→ Dowolny tryb (rekomendowany Quadriflow lub Instant Meshes) + **LOD Chain ON** (3–4 poziomy).

### Najlepsza jakość quadów automatycznie
→ **QuadWild** z zainstalowanym addonem QRemeshify. Scale Factor 1.0 dla medium, 0.4 dla high detail. Najwolniejszy, ale jakość najbliższa ZRemesherowi.

### Szybka redukcja istniejącej siatki
→ **Decimate** z Ratio 0.3–0.5. Nie zmienia topologii, tylko redukuje poly.

### Model z siatką nierównomiernie rozłożoną (np. po sculpt)
→ Dowolny tryb + **Smooth + Re-project** (8+ iteracji). Wyrówna gęstość bez zmiany kształtu.

### Chcesz kontrolować kierunek edge loopów
→ Narysuj stroke'i przed remeshem, włącz **Guidance Snap** dla twardych loopów ALBO **Guidance Field** dla miękkiego wpływu na przepływ quadów. Field działa najlepiej z Quadriflow lub Instant Meshes.

### Model z wyraźnymi detalami w jednych miejscach a płaski w innych
→ Włącz **Curvature Pre-pass** + Quadriflow z `Uwzględnij krzywiznę`. Siatka będzie gęstsza tam gdzie model jest ciekawy, a rzadsza na płaskich ścianach.

### Postać symetryczna (humanoid, pojazd)
→ Użyj **Stroke Symmetry** przy rysowaniu loopów (oś X). W Quadriflow włącz `Użyj Symetrii`.

---

## Typowe błędy i rozwiązania

| Problem | Przyczyna | Rozwiązanie |
|---|---|---|
| Voxel Remesh tworzy dziury | Model nie jest zamknięty (non-manifold) | Włącz **Mesh Healing** (domyślnie ON) — automatycznie wypełnia dziury przed remeshem |
| Quadriflow zawiesza się | Za duża liczba target faces przy skomplikowanym modelu | Zacznij od 2000 faces, zwiększaj stopniowo |
| Instant Meshes nie uruchamia się | Brak ścieżki do binarki | Wpisz pełną ścieżkę do `Instant Meshes.exe` w polu Binarka |
| Stroke Guidance nie działa | Guidance nie jest włączone | Upewnij się że przycisk „Użyj jako Guidance" jest aktywny przed kliknięciem Uruchom Retopo |
| Model zniknął z listy Target | Usunięty klawiszem Delete w viewporcie | Tool auto-czyści referencję — wybierz model ponownie |
| Wysokie „Dev. od HP" w metrykach | Siatka nie leży dokładnie na powierzchni | Włącz **Smooth + Re-project** z 5+ iteracjami |
| Niski wynik Kąt (Jacobian) | Quady są skrzywione (shear) | Zwiększ iteracje Smooth + Re-project lub dodaj więcej stroke'ów Field guidance w problematycznych strefach |
