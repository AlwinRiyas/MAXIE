import random


class RecommendationSkill:
    """Suggest a movie, series, song, or game from a curated offline
    catalog. Category comes from the spoken request; without one,
    MAXIE picks across everything."""

    CATALOG = {
        "movie": [
            ("The Matrix", "technical and stylish"),
            ("Interstellar", "deep and moving"),
            ("Dune", "epic and cinematic"),
            ("The Dark Knight", "intense and clever"),
            ("Oppenheimer", "weighty and historical"),
            ("Spirited Away", "whimsical and beautiful"),
        ],
        "movie_mega": [
            ("Godzilla Minus One", "visually stunning"),
            ("Everything Everywhere All at Once", "wildly inventive"),
        ],
        "series": [
            ("Breaking Bad", "tense from start to finish"),
            ("Arcane", "gorgeous and gripping"),
            ("Dark", "a mind-bending puzzle"),
            ("Severance", "strange and stylish"),
            ("Peaky Blinders", "sharp and stylish"),
            ("The Bear", "raw and rewarding"),
        ],
        "music": [
            ("Vulnerable - Coldplay", "warm and easy to loop"),
            ("Blinding Lights - The Weeknd", "a midnight drive classic"),
            ("Birds of a Feather - Billie Eilish", "soft and catchy"),
            ("Dance The Night - Dua Lipa", "pure energy"),
            ("Believer - Imagine Dragons", "pump-you-up"),
        ],
        "game": [
            ("Elden Ring", "a challenge worth taking"),
            ("Baldur's Gate 3", "endless choices"),
            ("Hades", "fast and addictive"),
            ("Stray", "charming and short"),
        ],
    }

    def recommend(self, text):
        text = text.lower()
        category = self._category(text)
        pool = self.CATALOG[category] if category else sum(
            self.CATALOG.values(), []
        )
        title, flavor = random.choice(pool)
        return f"How about {title}? I'm suggesting it because it's {flavor} — worth checking out."

    def _category(self, text):
        if any(word in text for word in ("movie", "film", "flick")):
            return "movie"
        if any(word in text for word in ("series", "show", "tv", "season")):
            return "series"
        if any(word in text for word in ("song", "music", "playlist",
                                         "album", "artist", "track")):
            return "music"
        if any(word in text for word in ("game", "playstation",
                                         "xbox", "nintendo")):
            return "game"
        return None