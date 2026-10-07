from dota2picker import heroes, items

by_name = {h.localized_name: h.id for h in heroes.all_heroes()}


def names(suggestions):
    return [s.item.name for s in suggestions]


def test_every_hero_has_valid_threats():
    tags = set(items.counters())
    for hero in heroes.all_heroes():
        threats = items.threats().get(hero.short_name)
        assert threats, hero.short_name
        assert set(threats) <= tags, hero.short_name


def test_every_counter_item_is_known():
    for tag, rule in items.counters().items():
        for key in rule["core"] + rule["support"]:
            assert key in items.all_items(), (tag, key)


def test_core_vs_evasion_and_invisibility():
    enemies = [by_name["Phantom Assassin"], by_name["Riki"]]
    out = items.suggest_items(by_name["Juggernaut"], enemies, position=1)
    top = names(out)
    assert "Monkey King Bar" in top[:3]
    assert "Dust of Appearance" in top
    mkb = next(s for s in out if s.item.key == "monkey_king_bar")
    assert mkb.answers[by_name["Phantom Assassin"]] == ["evasion"]


def test_support_gets_support_items():
    enemies = [by_name["Lion"], by_name["Lina"], by_name["Riki"]]
    out = names(items.suggest_items(by_name["Crystal Maiden"], enemies, position=5))
    assert "Glimmer Cape" in out[:3]
    assert "Black King Bar" not in out


def test_role_follows_main_position_when_none_chosen():
    cm, am = heroes.by_id()[by_name["Crystal Maiden"]], heroes.by_id()[by_name["Anti-Mage"]]
    assert items.role_for(cm, None) == "support"
    assert items.role_for(am, None) == "core"
    assert items.role_for(cm, 2) == "core"


def test_ranged_heroes_dont_get_melee_items():
    enemies = [by_name["Phantom Lancer"], by_name["Naga Siren"], by_name["Beastmaster"]]
    ranged = names(items.suggest_items(by_name["Drow Ranger"], enemies, position=1, limit=20))
    melee = names(items.suggest_items(by_name["Juggernaut"], enemies, position=1, limit=20))
    assert "Battle Fury" in melee and "Battle Fury" not in ranged


def test_items_that_answer_more_enemies_rank_higher():
    # Three magic-burst heroes: BKB answers all of them.
    enemies = [by_name["Lion"], by_name["Lina"], by_name["Zeus"]]
    out = items.suggest_items(by_name["Sven"], enemies, position=1)
    assert out[0].item.name == "Black King Bar"
    assert len(out[0].answers) == 3


def test_no_enemies_no_items():
    assert items.suggest_items(by_name["Sven"], []) == []


def test_specific_answers_beat_generic_right_click_items():
    # Manta (dispels Riki's silence) should outrank generic damage items like Butterfly.
    enemies = [by_name["Phantom Assassin"], by_name["Riki"], by_name["Lion"]]
    top = names(items.suggest_items(by_name["Juggernaut"], enemies, position=1))
    assert "Manta Style" in top
    assert "Butterfly" not in top


def test_break_against_passive_heroes():
    enemies = [by_name["Slark"], by_name["Huskar"]]
    out = names(items.suggest_items(by_name["Sven"], enemies, position=1))
    assert out[0] == "Silver Edge"
    # Dust doesn't reveal Shadow Dance, so it isn't suggested against Slark.
    assert "Dust of Appearance" not in out


def test_hero_rules_name_real_heroes_and_items():
    rules = items._hero_rules()
    known_heroes = {h.short_name for h in heroes.all_heroes()}
    groups = list(rules["groups"].values()) + list(rules["heroes"].values())
    for group in groups:
        assert set(group["items"]) <= set(items.all_items()), group["why"]
    for group in rules["groups"].values():
        assert set(group["heroes"]) <= known_heroes, group["why"]
    assert set(rules["heroes"]) <= known_heroes


def test_meepo_gets_no_one_body_items():
    # Lion, Lina and Shadow Shaman would normally point a core at BKB, Linken's and Aeon Disk.
    enemies = [by_name["Lion"], by_name["Lina"], by_name["Shadow Shaman"], by_name["Phantom Assassin"]]
    out = names(items.suggest_items(by_name["Meepo"], enemies, position=2, limit=20))
    for bad in ["Black King Bar", "Aeon Disk", "Linken's Sphere", "Monkey King Bar"]:
        assert bad not in out
    assert "Pipe of Insight" in out  # its barrier covers every clone


def test_spell_cores_skip_attack_items():
    enemies = [by_name["Phantom Assassin"], by_name["Phantom Lancer"]]
    zeus = names(items.suggest_items(by_name["Zeus"], enemies, position=2, limit=20))
    sven = names(items.suggest_items(by_name["Sven"], enemies, position=1, limit=20))
    assert "Monkey King Bar" in sven and "Monkey King Bar" not in zeus
    assert "Mjollnir" not in zeus and "Shiva's Guard" in zeus
