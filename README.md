# Misja: Krzyś

Aplikacja webowa (frontend + backend) do monitorowania funkcji życiowych Krzysia
i wysyłania mu wiadomości.

<img width="800" height="600" alt="dashboard" src="https://github.com/user-attachments/assets/7b7befba-3492-4eba-95ac-f9de51b7a51d" />

## Uruchomienie

Wymagania: Python 3.10+

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Otwórz w przeglądarce: http://127.0.0.1:5000

## Funkcje

- Symulowane dane Krzysia: tlen, tętno, temperatura, energia, nastrój;
  pomiary powstają w tle co 1,5 s, niezależnie od otwartych kart.
- Widżety: wykres, pasek (gauge) i duża wartość; dane odświeżają się
  automatycznie (polling), bez przeładowania strony.
- Wysyłanie wiadomości do Krzysia i ich historia.
- Trwała historia danych i wiadomości (SQLite, `history.db`), przeżywa
  restart backendu.
- Dynamiczna konfiguracja z `config.json`: decyduje, co i w jakiej kolejności
  się wyświetla oraz jaki jest typ widżetu. Zmiana pliku działa bez restartu
  backendu - wystarczy odświeżyć przeglądarkę.

## Konfiguracja (`config.json`)

- `refresh_interval_ms` - jak często frontend pobiera dane.
- `params` - lista parametrów w kolejności wyświetlania:
  - `key`, `label`, `unit` - powiązanie z danymi i opis,
  - `widget` - `chart`, `gauge` lub `value`,
  - `min`, `max` - zakres dla widżetu.

## Endpointy

| Metoda | Ścieżka        | Opis                                        |
|--------|----------------|---------------------------------------------|
| GET    | `/`            | Frontend                                    |
| GET    | `/api/config`  | Konfiguracja z `config.json`                |
| GET    | `/api/data`    | Najnowszy pomiar                            |
| POST   | `/api/message` | Zapis wiadomości (`{"text": "..."}`)        |
| GET    | `/api/messages`| Historia wiadomości (`?limit=50`)           |
| GET    | `/api/history` | Historia danych i wiadomości (`?limit=50`)  |

## Struktura

```
app.py               backend Flask
config.json          konfiguracja widoku
requirements.txt     zależności
templates/index.html strona
static/app.js        logika frontendu
static/style.css     wygląd
static/favicon.ico   ikona
```
