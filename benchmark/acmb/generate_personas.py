from __future__ import annotations

import json
from pathlib import Path


PERSONAS_DIR = Path.home() / ".akashik" / "data" / "benchmarks" / "acmb" / "personas"
QUERIES_DIR = Path.home() / ".akashik" / "data" / "benchmarks" / "acmb" / "queries"


def _persona(persona_id: str, name: str, age_range: str, occupation: str, domain: str, stable_traits: dict,
             facts: list[dict], commitments: list[dict], sessions: list[dict]) -> dict:
    return {
        "persona_id": persona_id,
        "name": name,
        "age_range": age_range,
        "occupation": occupation,
        "domain": domain,
        "stable_traits": stable_traits,
        "facts": facts,
        "commitments": commitments,
        "sessions": sessions,
    }


def _queries(persona_id: str, queries: list[dict]) -> dict:
    return {"persona_id": persona_id, "queries": queries}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_personas() -> list[dict]:
    return [
        _persona(
            "persona_001",
            "Alex",
            "30s",
            "software engineer",
            "personal_life",
            {"communication_style": "direct", "location_origin": "Chicago"},
            [
                {"fact_id": "f001", "attribute": "location", "value": "Chicago", "natural_language": "I live in Chicago, in Logan Square.", "introduced_session": 1, "introduced_turn": "t003", "superseded_session": 3, "superseded_turn": "t023"},
                {"fact_id": "f002", "attribute": "location", "value": "Denver", "natural_language": "I moved to Denver last month and I'm still getting used to the altitude.", "introduced_session": 3, "introduced_turn": "t023", "superseded_session": None, "superseded_turn": None},
                {"fact_id": "f003", "attribute": "weekend_activity", "value": "skiing", "natural_language": "Most winter weekends I head up to ski if I can.", "introduced_session": 2, "introduced_turn": "t012", "superseded_session": 4, "superseded_turn": "t031"},
                {"fact_id": "f004", "attribute": "weekend_activity", "value": "trail running", "natural_language": "Lately I've traded ski trips for trail runs on the weekends.", "introduced_session": 4, "introduced_turn": "t031", "superseded_session": None, "superseded_turn": None},
            ],
            [{"commitment_id": "c001", "description": "help find trail running gear", "opened_session": 4, "opened_turn": "t034", "closed_session": None, "closed_turn": None}],
            [
                {"session_id": "s1", "session_number": 1, "session_type": "normal", "simulated_date": "2026-01-05", "turns": [
                    {"turn_id": "t001", "actor": "user", "content": "I'm trying to find a coffee spot near my apartment that stays quiet in the mornings.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t002", "actor": "assistant", "content": "Happy to help. What part of town are you in?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t003", "actor": "user", "content": "I live in Chicago, in Logan Square, so somewhere I can walk to would be ideal.", "ground_truth_facts": ["f001"], "revises_facts": []},
                    {"turn_id": "t004", "actor": "assistant", "content": "That gives me a useful anchor. Do you care more about espresso or atmosphere?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t005", "actor": "user", "content": "Atmosphere, mostly. I usually need a calm place before I start work.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t006", "actor": "assistant", "content": "Noted. I'll keep neighborhood suggestions walkable and low-key.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s2", "session_number": 2, "session_type": "drift", "simulated_date": "2026-01-26", "turns": [
                    {"turn_id": "t011", "actor": "user", "content": "Work has been noisy, so I'm daydreaming about winter weekends instead.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t012", "actor": "user", "content": "Most winter weekends I head up to ski if I can. That's usually how I reset.", "ground_truth_facts": ["f003"], "revises_facts": []},
                    {"turn_id": "t013", "actor": "assistant", "content": "That tracks. You tend to recharge by getting outside rather than staying in the city.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t014", "actor": "user", "content": "Exactly, although I'm also trying not to spend every Saturday in the car.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t015", "actor": "assistant", "content": "Makes sense. If that changes, we can rethink your weekend routine.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t016", "actor": "user", "content": "For now it's still my default.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s3", "session_number": 3, "session_type": "contradiction", "simulated_date": "2026-03-02", "turns": [
                    {"turn_id": "t021", "actor": "user", "content": "Quick update: I was about to say Chicago again out of habit, but that's old news now.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t022", "actor": "assistant", "content": "Sounds like something changed. What should I use going forward?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t023", "actor": "user", "content": "I moved to Denver last month and I'm still getting used to the altitude.", "ground_truth_facts": ["f002"], "revises_facts": ["f001"]},
                    {"turn_id": "t024", "actor": "assistant", "content": "Got it. Denver is the current location; Chicago is now historical context.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t025", "actor": "user", "content": "Exactly. New city, same job, different lungs.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t026", "actor": "assistant", "content": "I'll keep that in mind for anything outdoors or weather related.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s4", "session_number": 4, "session_type": "normal", "simulated_date": "2026-03-25", "turns": [
                    {"turn_id": "t031", "actor": "user", "content": "Another change: lately I've traded ski trips for trail runs on the weekends.", "ground_truth_facts": ["f004"], "revises_facts": ["f003"]},
                    {"turn_id": "t032", "actor": "assistant", "content": "Trail running fits Denver pretty well. Are you enjoying it?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t033", "actor": "user", "content": "Yeah, and it feels easier to do without planning a full day around it.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t034", "actor": "assistant", "content": "I'll help find trail running gear if you want to build out a setup.", "ground_truth_facts": ["c001"], "revises_facts": []},
                    {"turn_id": "t035", "actor": "user", "content": "Please do. I need better layers and probably shoes with more grip.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t036", "actor": "assistant", "content": "Noted. We'll keep weather and elevation in mind.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s5", "session_number": 5, "session_type": "noise", "simulated_date": "2026-04-10", "turns": [
                    {"turn_id": "t041", "actor": "user", "content": "I spent half the morning comparing cast-iron pans and now my browser is a mess.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t042", "actor": "assistant", "content": "That sounds like a very specific rabbit hole. Looking for durability or price?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t043", "actor": "user", "content": "Mostly durability, though now I'm wondering whether seasoning is worth the hassle.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t044", "actor": "assistant", "content": "We can untangle cookware tradeoffs if you want, but I won't assume this replaces your other priorities.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t045", "actor": "user", "content": "Thanks. This one was mostly me procrastinating.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t046", "actor": "assistant", "content": "Fair enough. Sometimes research is just structured avoidance.", "ground_truth_facts": [], "revises_facts": []},
                ]},
            ],
        ),
        _persona(
            "persona_002",
            "Jordan",
            "30s",
            "designer",
            "work_projects",
            {"communication_style": "collaborative", "team_size": "mid-sized"},
            [
                {"fact_id": "f001", "attribute": "role", "value": "mobile designer", "natural_language": "I’m leading mobile product design right now.", "introduced_session": 1, "introduced_turn": "t003", "superseded_session": 3, "superseded_turn": "t023"},
                {"fact_id": "f002", "attribute": "role", "value": "design manager", "natural_language": "I just stepped into a design manager role.", "introduced_session": 3, "introduced_turn": "t023", "superseded_session": None, "superseded_turn": None},
                {"fact_id": "f003", "attribute": "active_project", "value": "mobile redesign", "natural_language": "The big push this quarter is our mobile redesign.", "introduced_session": 2, "introduced_turn": "t012", "superseded_session": 4, "superseded_turn": "t031"},
                {"fact_id": "f004", "attribute": "active_project", "value": "web workspace pivot", "natural_language": "We pivoted and now the urgent project is the web workspace.", "introduced_session": 4, "introduced_turn": "t031", "superseded_session": None, "superseded_turn": None},
            ],
            [{"commitment_id": "c001", "description": "help draft stakeholder update for web workspace pivot", "opened_session": 4, "opened_turn": "t034", "closed_session": None, "closed_turn": None}],
            [
                {"session_id": "s1", "session_number": 1, "session_type": "normal", "simulated_date": "2026-01-08", "turns": [
                    {"turn_id": "t001", "actor": "user", "content": "I need help framing a rough week without making it sound like I'm complaining.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t002", "actor": "assistant", "content": "We can do that. What kind of work are you juggling?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t003", "actor": "user", "content": "I’m leading mobile product design right now, so every conversation becomes a prioritization fight.", "ground_truth_facts": ["f001"], "revises_facts": []},
                    {"turn_id": "t004", "actor": "assistant", "content": "That gives us useful context. We can make the update sound grounded instead of defensive.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t005", "actor": "user", "content": "That's exactly what I want.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t006", "actor": "assistant", "content": "Then we'll keep the tone calm and specific.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s2", "session_number": 2, "session_type": "drift", "simulated_date": "2026-01-28", "turns": [
                    {"turn_id": "t011", "actor": "user", "content": "The big push this quarter is our mobile redesign, and every mockup review runs long.", "ground_truth_facts": ["f003"], "revises_facts": []},
                    {"turn_id": "t012", "actor": "assistant", "content": "So the redesign is still the dominant workstream.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t013", "actor": "user", "content": "Yes, although suddenly everyone also wants roadmap clarity.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t014", "actor": "assistant", "content": "That usually means the project is stressing the org in ways beyond design.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t015", "actor": "user", "content": "Exactly. It's less about pixels than alignment.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t016", "actor": "assistant", "content": "Then that's the story we should tell.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s3", "session_number": 3, "session_type": "contradiction", "simulated_date": "2026-02-19", "turns": [
                    {"turn_id": "t021", "actor": "user", "content": "I almost said I'm still an IC, but that changed this week.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t022", "actor": "assistant", "content": "Okay, what title should I use now?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t023", "actor": "user", "content": "I just stepped into a design manager role.", "ground_truth_facts": ["f002"], "revises_facts": ["f001"]},
                    {"turn_id": "t024", "actor": "assistant", "content": "That shifts the framing a lot. You’re now balancing team health with delivery.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t025", "actor": "user", "content": "Exactly, and I need my updates to reflect that.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t026", "actor": "assistant", "content": "Understood. I’ll anchor future advice in the manager perspective.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s4", "session_number": 4, "session_type": "normal", "simulated_date": "2026-03-15", "turns": [
                    {"turn_id": "t031", "actor": "user", "content": "We pivoted and now the urgent project is the web workspace instead of the mobile redesign.", "ground_truth_facts": ["f004"], "revises_facts": ["f003"]},
                    {"turn_id": "t032", "actor": "assistant", "content": "That is a meaningful change. Different stakeholders too?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t033", "actor": "user", "content": "Yes, and the executive audience suddenly got much closer.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t034", "actor": "assistant", "content": "I can help draft the stakeholder update for the web workspace pivot.", "ground_truth_facts": ["c001"], "revises_facts": []},
                    {"turn_id": "t035", "actor": "user", "content": "Please do. I want it crisp and not alarmist.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t036", "actor": "assistant", "content": "We’ll keep it concrete and steady.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s5", "session_number": 5, "session_type": "noise", "simulated_date": "2026-04-06", "turns": [
                    {"turn_id": "t041", "actor": "user", "content": "I spent lunch debating whether a standing desk mat is secretly a scam.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t042", "actor": "assistant", "content": "That’s the kind of question the internet can make worse.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t043", "actor": "user", "content": "Exactly. Half the reviews sound life-changing and half sound paid for.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t044", "actor": "assistant", "content": "A familiar modern problem.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t045", "actor": "user", "content": "Anyway, it was a nice break from everything else.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t046", "actor": "assistant", "content": "Sometimes minor gear indecision is a relief valve.", "ground_truth_facts": [], "revises_facts": []},
                ]},
            ],
        ),
        _persona(
            "persona_003",
            "Sam",
            "40s",
            "photographer",
            "devices_purchases",
            {"communication_style": "practical", "location_origin": "Portland"},
            [
                {"fact_id": "f001", "attribute": "camera", "value": "Fuji X-T3", "natural_language": "I’ve been shooting on a Fuji X-T3 for years.", "introduced_session": 1, "introduced_turn": "t003", "superseded_session": 3, "superseded_turn": "t023"},
                {"fact_id": "f002", "attribute": "camera", "value": "Sony A7 IV", "natural_language": "I finally upgraded to a Sony A7 IV.", "introduced_session": 3, "introduced_turn": "t023", "superseded_session": None, "superseded_turn": None},
                {"fact_id": "f003", "attribute": "laptop", "value": "aging MacBook Pro", "natural_language": "My old MacBook Pro is wheezing through Lightroom exports.", "introduced_session": 2, "introduced_turn": "t012", "superseded_session": 4, "superseded_turn": "t031"},
                {"fact_id": "f004", "attribute": "laptop", "value": "M3 MacBook Pro", "natural_language": "I replaced the laptop with an M3 MacBook Pro.", "introduced_session": 4, "introduced_turn": "t031", "superseded_session": None, "superseded_turn": None},
            ],
            [{"commitment_id": "c001", "description": "help compare travel camera straps", "opened_session": 4, "opened_turn": "t034", "closed_session": None, "closed_turn": None}],
            [
                {"session_id": "s1", "session_number": 1, "session_type": "normal", "simulated_date": "2026-01-04", "turns": [
                    {"turn_id": "t001", "actor": "user", "content": "I have a travel shoot coming up and I'm trying not to overpack for it.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t002", "actor": "assistant", "content": "What gear are you starting from?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t003", "actor": "user", "content": "I’ve been shooting on a Fuji X-T3 for years, so that body is still my baseline.", "ground_truth_facts": ["f001"], "revises_facts": []},
                    {"turn_id": "t004", "actor": "assistant", "content": "That gives us a familiar weight and lens profile to work around.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t005", "actor": "user", "content": "Exactly, I mostly want to stay nimble.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t006", "actor": "assistant", "content": "Then let's optimize around portability first.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s2", "session_number": 2, "session_type": "drift", "simulated_date": "2026-01-24", "turns": [
                    {"turn_id": "t011", "actor": "user", "content": "Separate rant: my old MacBook Pro is wheezing through Lightroom exports.", "ground_truth_facts": ["f003"], "revises_facts": []},
                    {"turn_id": "t012", "actor": "assistant", "content": "That can become the bottleneck faster than the camera does.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t013", "actor": "user", "content": "Exactly. I can live with a camera compromise before I can live with another spinning export wheel.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t014", "actor": "assistant", "content": "Then the computer problem may deserve attention first.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t015", "actor": "user", "content": "I think you're right.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t016", "actor": "assistant", "content": "We can sequence the upgrades when you're ready.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s3", "session_number": 3, "session_type": "contradiction", "simulated_date": "2026-02-16", "turns": [
                    {"turn_id": "t021", "actor": "user", "content": "I almost said I'd keep milking the Fuji for another year, but I changed my mind.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t022", "actor": "assistant", "content": "What did you end up doing?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t023", "actor": "user", "content": "I finally upgraded to a Sony A7 IV.", "ground_truth_facts": ["f002"], "revises_facts": ["f001"]},
                    {"turn_id": "t024", "actor": "assistant", "content": "That's a real shift. Different ergonomics, different lens decisions.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t025", "actor": "user", "content": "Yeah, but the autofocus alone made the decision feel easy.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t026", "actor": "assistant", "content": "Good. I'll treat Sony as the current body going forward.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s4", "session_number": 4, "session_type": "normal", "simulated_date": "2026-03-18", "turns": [
                    {"turn_id": "t031", "actor": "user", "content": "And I replaced the laptop with an M3 MacBook Pro, so editing isn't painful anymore.", "ground_truth_facts": ["f004"], "revises_facts": ["f003"]},
                    {"turn_id": "t032", "actor": "assistant", "content": "That should make travel culling and exports much less annoying.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t033", "actor": "user", "content": "It already has. The bottleneck moved back to me choosing photos.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t034", "actor": "assistant", "content": "If you want, I can help compare travel camera straps next.", "ground_truth_facts": ["c001"], "revises_facts": []},
                    {"turn_id": "t035", "actor": "user", "content": "Please. The new body feels different enough that my old strap setup is awkward.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t036", "actor": "assistant", "content": "We'll optimize for comfort and quick access.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s5", "session_number": 5, "session_type": "noise", "simulated_date": "2026-04-07", "turns": [
                    {"turn_id": "t041", "actor": "user", "content": "I got distracted by a thread about airport snacks and suddenly had opinions.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t042", "actor": "assistant", "content": "Airport snacks can produce surprisingly strong loyalties.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t043", "actor": "user", "content": "Exactly. I didn't realize how much I care about decent almonds until now.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t044", "actor": "assistant", "content": "An unexpectedly intense subculture.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t045", "actor": "user", "content": "A harmless one, at least.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t046", "actor": "assistant", "content": "Those are worth keeping.", "ground_truth_facts": [], "revises_facts": []},
                ]},
            ],
        ),
        _persona(
            "persona_004",
            "Morgan",
            "30s",
            "runner",
            "health_fitness",
            {"communication_style": "reflective", "location_origin": "Austin"},
            [
                {"fact_id": "f001", "attribute": "training_status", "value": "marathon build", "natural_language": "I was in the middle of marathon training.", "introduced_session": 1, "introduced_turn": "t003", "superseded_session": 2, "superseded_turn": "t013"},
                {"fact_id": "f002", "attribute": "injury", "value": "hamstring strain", "natural_language": "I strained my hamstring and had to stop running for a while.", "introduced_session": 2, "introduced_turn": "t013", "superseded_session": 4, "superseded_turn": "t031"},
                {"fact_id": "f003", "attribute": "recovery_status", "value": "returning to easy miles", "natural_language": "I’m back to easy runs and rebuilding slowly.", "introduced_session": 4, "introduced_turn": "t031", "superseded_session": None, "superseded_turn": None},
                {"fact_id": "f004", "attribute": "current_goal", "value": "return to training", "natural_language": "Right now the goal is just a steady return to training.", "introduced_session": 4, "introduced_turn": "t033", "superseded_session": None, "superseded_turn": None},
            ],
            [{"commitment_id": "c001", "description": "help sketch a cautious return-to-run week", "opened_session": 4, "opened_turn": "t034", "closed_session": None, "closed_turn": None}],
            [
                {"session_id": "s1", "session_number": 1, "session_type": "normal", "simulated_date": "2026-01-03", "turns": [
                    {"turn_id": "t001", "actor": "user", "content": "I'm trying to figure out whether my long run schedule is too aggressive.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t002", "actor": "assistant", "content": "What kind of training block are you in?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t003", "actor": "user", "content": "I was in the middle of marathon training, which is why I'm watching every workout so closely.", "ground_truth_facts": ["f001"], "revises_facts": []},
                    {"turn_id": "t004", "actor": "assistant", "content": "That context matters. Marathon fatigue can hide in plain sight.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t005", "actor": "user", "content": "Exactly. I don't want to be stubborn about it.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t006", "actor": "assistant", "content": "Then we'll lean cautious.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s2", "session_number": 2, "session_type": "contradiction", "simulated_date": "2026-01-25", "turns": [
                    {"turn_id": "t011", "actor": "user", "content": "Well, marathon talk is outdated for the moment.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t012", "actor": "assistant", "content": "What happened?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t013", "actor": "user", "content": "I strained my hamstring and had to stop running for a while.", "ground_truth_facts": ["f002"], "revises_facts": ["f001"]},
                    {"turn_id": "t014", "actor": "assistant", "content": "Then recovery takes priority over the old plan.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t015", "actor": "user", "content": "Reluctantly, yes.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t016", "actor": "assistant", "content": "We'll recalibrate around healing, not mileage.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s3", "session_number": 3, "session_type": "noise", "simulated_date": "2026-02-18", "turns": [
                    {"turn_id": "t021", "actor": "user", "content": "I lost ten minutes yesterday deciding whether soup counts as a real lunch.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t022", "actor": "assistant", "content": "That depends on the soup and your standards.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t023", "actor": "user", "content": "Both were apparently in question.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t024", "actor": "assistant", "content": "A surprisingly philosophical midday problem.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t025", "actor": "user", "content": "Exactly. No grand lesson, just indecision.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t026", "actor": "assistant", "content": "Sometimes that's the whole story.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s4", "session_number": 4, "session_type": "normal", "simulated_date": "2026-03-20", "turns": [
                    {"turn_id": "t031", "actor": "user", "content": "I’m back to easy runs and rebuilding slowly, which is better than where I was a month ago.", "ground_truth_facts": ["f003"], "revises_facts": ["f002"]},
                    {"turn_id": "t032", "actor": "assistant", "content": "That’s progress. Slow is exactly what you want right now.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t033", "actor": "user", "content": "Right now the goal is just a steady return to training.", "ground_truth_facts": ["f004"], "revises_facts": []},
                    {"turn_id": "t034", "actor": "assistant", "content": "I can help sketch a cautious return-to-run week.", "ground_truth_facts": ["c001"], "revises_facts": []},
                    {"turn_id": "t035", "actor": "user", "content": "That would help. I don't trust my own enthusiasm yet.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t036", "actor": "assistant", "content": "We'll bias toward patience.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s5", "session_number": 5, "session_type": "drift", "simulated_date": "2026-04-11", "turns": [
                    {"turn_id": "t041", "actor": "user", "content": "A friend asked me to judge a backyard chili cookoff, which feels like a lot of responsibility.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t042", "actor": "assistant", "content": "That is a dangerous amount of soft power.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t043", "actor": "user", "content": "Exactly. I'm pretending there's a science to it.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t044", "actor": "assistant", "content": "There probably is, but everyone will ignore it if they lose.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t045", "actor": "user", "content": "That sounds right.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t046", "actor": "assistant", "content": "At least you'll get lunch out of it.", "ground_truth_facts": [], "revises_facts": []},
                ]},
            ],
        ),
        _persona(
            "persona_005",
            "Riley",
            "30s",
            "writer",
            "preferences",
            {"communication_style": "thoughtful", "location_origin": "Seattle"},
            [
                {"fact_id": "f001", "attribute": "writing_app", "value": "Ulysses", "natural_language": "I’ve been drafting everything in Ulysses.", "introduced_session": 1, "introduced_turn": "t003", "superseded_session": 3, "superseded_turn": "t023"},
                {"fact_id": "f002", "attribute": "writing_app", "value": "Obsidian", "natural_language": "I switched and now I’m writing in Obsidian.", "introduced_session": 3, "introduced_turn": "t023", "superseded_session": None, "superseded_turn": None},
                {"fact_id": "f003", "attribute": "feedback_style", "value": "gentle", "natural_language": "When you critique something, keep the tone gentle.", "introduced_session": 2, "introduced_turn": "t012", "superseded_session": 4, "superseded_turn": "t031"},
                {"fact_id": "f004", "attribute": "feedback_style", "value": "direct but concise", "natural_language": "I still want honesty, but make the feedback direct and concise.", "introduced_session": 4, "introduced_turn": "t031", "superseded_session": None, "superseded_turn": None},
            ],
            [{"commitment_id": "c001", "description": "help compare Obsidian writing workflow plugins", "opened_session": 4, "opened_turn": "t034", "closed_session": None, "closed_turn": None}],
            [
                {"session_id": "s1", "session_number": 1, "session_type": "normal", "simulated_date": "2026-01-06", "turns": [
                    {"turn_id": "t001", "actor": "user", "content": "I'm trying to make my writing workflow less fussy this year.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t002", "actor": "assistant", "content": "What are you using now?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t003", "actor": "user", "content": "I’ve been drafting everything in Ulysses, mostly because it gets out of my way.", "ground_truth_facts": ["f001"], "revises_facts": []},
                    {"turn_id": "t004", "actor": "assistant", "content": "That suggests simplicity matters more to you than feature depth.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t005", "actor": "user", "content": "Exactly. I like tools that disappear while I work.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t006", "actor": "assistant", "content": "Then we'll keep friction low in any suggestion.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s2", "session_number": 2, "session_type": "normal", "simulated_date": "2026-01-29", "turns": [
                    {"turn_id": "t011", "actor": "user", "content": "Also, when you critique something, keep the tone gentle. I take in notes better that way.", "ground_truth_facts": ["f003"], "revises_facts": []},
                    {"turn_id": "t012", "actor": "assistant", "content": "Understood. Gentle, constructive feedback works better for you.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t013", "actor": "user", "content": "Exactly. I don't need sugarcoating, just less blunt force.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t014", "actor": "assistant", "content": "That’s a useful distinction.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t015", "actor": "user", "content": "I try to be clear about it now.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t016", "actor": "assistant", "content": "And I’ll respect it.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s3", "session_number": 3, "session_type": "contradiction", "simulated_date": "2026-02-20", "turns": [
                    {"turn_id": "t021", "actor": "user", "content": "I thought I'd stay with Ulysses, but that didn't last.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t022", "actor": "assistant", "content": "What changed?", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t023", "actor": "user", "content": "I switched and now I’m writing in Obsidian.", "ground_truth_facts": ["f002"], "revises_facts": ["f001"]},
                    {"turn_id": "t024", "actor": "assistant", "content": "Interesting. So linked notes started to matter more than pure minimalism.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t025", "actor": "user", "content": "Exactly. I still want focus, but the connections are useful.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t026", "actor": "assistant", "content": "Then Obsidian is the current writing app in my model of your setup.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s4", "session_number": 4, "session_type": "drift", "simulated_date": "2026-03-19", "turns": [
                    {"turn_id": "t031", "actor": "user", "content": "One more correction: I still want honesty, but make the feedback direct and concise.", "ground_truth_facts": ["f004"], "revises_facts": ["f003"]},
                    {"turn_id": "t032", "actor": "assistant", "content": "So not harsh, but sharper and shorter than before.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t033", "actor": "user", "content": "Exactly. Gentle can drift into vague, and that stops helping.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t034", "actor": "assistant", "content": "I can help compare Obsidian writing workflow plugins if that would support the new setup.", "ground_truth_facts": ["c001"], "revises_facts": []},
                    {"turn_id": "t035", "actor": "user", "content": "Yes, especially anything that helps me move from notes to drafts faster.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t036", "actor": "assistant", "content": "We'll keep it practical.", "ground_truth_facts": [], "revises_facts": []},
                ]},
                {"session_id": "s5", "session_number": 5, "session_type": "noise", "simulated_date": "2026-04-12", "turns": [
                    {"turn_id": "t041", "actor": "user", "content": "I got weirdly invested in ranking neighborhood bookstores by creaky-floorboard charm.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t042", "actor": "assistant", "content": "That is a very writerly side quest.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t043", "actor": "user", "content": "I know, and I refuse to apologize for it.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t044", "actor": "assistant", "content": "Nor should you.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t045", "actor": "user", "content": "At least it kept me offline for an hour.", "ground_truth_facts": [], "revises_facts": []},
                    {"turn_id": "t046", "actor": "assistant", "content": "That alone sounds like a win.", "ground_truth_facts": [], "revises_facts": []},
                ]},
            ],
        ),
    ]


def build_queries() -> list[dict]:
    return [
        _queries("persona_001", [
            {"query_id": "q001", "session_number": 5, "turn_before": "t041", "query_text": "where do I live now?", "query_type": "current_state", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Old Chicago location is a distractor; Denver is current."},
            {"query_id": "q002", "session_number": 5, "turn_before": "t042", "query_text": "what outdoor thing am I doing on weekends lately?", "query_type": "paraphrase", "must_include": ["f004"], "must_exclude": ["f003"], "hard_distractors": ["f003"], "should_include": ["f002"], "expected_current": ["f004"], "answer_type": "factual", "adversarial_notes": "Stored wording says trail runs, not outdoor thing."},
            {"query_id": "q003", "session_number": 5, "turn_before": "t043", "query_text": "what did you say you'd help me shop for?", "query_type": "commitment", "must_include": ["c001"], "must_exclude": [], "hard_distractors": [], "should_include": ["f004"], "expected_current": [], "answer_type": "commitment", "adversarial_notes": "Open assistant commitment should surface."},
            {"query_id": "q004", "session_number": 5, "turn_before": "t044", "query_text": "what city am I based in these days?", "query_type": "noise_robustness", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001", "f003"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Relevant fact is older and there is cookware noise in the current session."},
        ]),
        _queries("persona_002", [
            {"query_id": "q001", "session_number": 5, "turn_before": "t041", "query_text": "what role am I in now?", "query_type": "current_state", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Old IC role should be excluded."},
            {"query_id": "q002", "session_number": 5, "turn_before": "t042", "query_text": "which product surface became the priority after the pivot?", "query_type": "paraphrase", "must_include": ["f004"], "must_exclude": ["f003"], "hard_distractors": ["f003"], "should_include": ["f002"], "expected_current": ["f004"], "answer_type": "factual", "adversarial_notes": "Stored wording says web workspace; query paraphrases it."},
            {"query_id": "q003", "session_number": 5, "turn_before": "t043", "query_text": "what follow-up did you offer to help me prepare?", "query_type": "commitment", "must_include": ["c001"], "must_exclude": [], "hard_distractors": [], "should_include": ["f004"], "expected_current": [], "answer_type": "commitment", "adversarial_notes": "Commitment is the stakeholder update support."},
            {"query_id": "q004", "session_number": 5, "turn_before": "t044", "query_text": "what project is actually urgent now?", "query_type": "noise_robustness", "must_include": ["f004"], "must_exclude": ["f003"], "hard_distractors": ["f003"], "should_include": [], "expected_current": ["f004"], "answer_type": "factual", "adversarial_notes": "Must retrieve through desk-mat noise."},
        ]),
        _queries("persona_003", [
            {"query_id": "q001", "session_number": 5, "turn_before": "t041", "query_text": "which camera am I using now?", "query_type": "current_state", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Fuji should not be treated as current."},
            {"query_id": "q002", "session_number": 5, "turn_before": "t042", "query_text": "what computer did I end up replacing the old one with?", "query_type": "paraphrase", "must_include": ["f004"], "must_exclude": ["f003"], "hard_distractors": ["f003"], "should_include": [], "expected_current": ["f004"], "answer_type": "factual", "adversarial_notes": "Stored wording says M3 MacBook Pro."},
            {"query_id": "q003", "session_number": 5, "turn_before": "t043", "query_text": "what gear comparison did you say you'd help with next?", "query_type": "commitment", "must_include": ["c001"], "must_exclude": [], "hard_distractors": [], "should_include": ["f002"], "expected_current": [], "answer_type": "commitment", "adversarial_notes": "Open commitment is about travel straps."},
            {"query_id": "q004", "session_number": 5, "turn_before": "t044", "query_text": "what camera body am I carrying these days?", "query_type": "noise_robustness", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001", "f003"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Needs to survive airport-snack noise and older device chatter."},
        ]),
        _queries("persona_004", [
            {"query_id": "q001", "session_number": 5, "turn_before": "t041", "query_text": "what am I focused on with running right now?", "query_type": "current_state", "must_include": ["f004"], "must_exclude": ["f001", "f002"], "hard_distractors": ["f001", "f002"], "should_include": ["f003"], "expected_current": ["f004"], "answer_type": "factual", "adversarial_notes": "Training goal is now return-to-run, not marathon buildup or injury stop."},
            {"query_id": "q002", "session_number": 5, "turn_before": "t042", "query_text": "what phase of comeback am I in?", "query_type": "paraphrase", "must_include": ["f003"], "must_exclude": ["f002"], "hard_distractors": ["f002"], "should_include": ["f004"], "expected_current": ["f003"], "answer_type": "factual", "adversarial_notes": "Paraphrases easy runs and gradual rebuild."},
            {"query_id": "q003", "session_number": 5, "turn_before": "t043", "query_text": "what recovery planning did you offer to help with?", "query_type": "commitment", "must_include": ["c001"], "must_exclude": [], "hard_distractors": [], "should_include": ["f004"], "expected_current": [], "answer_type": "commitment", "adversarial_notes": "Assistant commitment should remain open."},
            {"query_id": "q004", "session_number": 5, "turn_before": "t044", "query_text": "am I still injured or back to running?", "query_type": "noise_robustness", "must_include": ["f003"], "must_exclude": ["f002"], "hard_distractors": ["f002"], "should_include": ["f004"], "expected_current": ["f003"], "answer_type": "factual", "adversarial_notes": "Recovery fact must surface through chili-cookoff noise."},
        ]),
        _queries("persona_005", [
            {"query_id": "q001", "session_number": 5, "turn_before": "t041", "query_text": "which writing app am I using now?", "query_type": "current_state", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Ulysses is old state; Obsidian is current."},
            {"query_id": "q002", "session_number": 5, "turn_before": "t042", "query_text": "how do I want critique delivered these days?", "query_type": "paraphrase", "must_include": ["f004"], "must_exclude": ["f003"], "hard_distractors": ["f003"], "should_include": [], "expected_current": ["f004"], "answer_type": "factual", "adversarial_notes": "Query wording differs from stored direct-and-concise phrasing."},
            {"query_id": "q003", "session_number": 5, "turn_before": "t043", "query_text": "what tool-follow-up did you offer after I switched apps?", "query_type": "commitment", "must_include": ["c001"], "must_exclude": [], "hard_distractors": [], "should_include": ["f002"], "expected_current": [], "answer_type": "commitment", "adversarial_notes": "Open commitment is plugin/workflow help."},
            {"query_id": "q004", "session_number": 5, "turn_before": "t044", "query_text": "what writing software is my current setup built around?", "query_type": "noise_robustness", "must_include": ["f002"], "must_exclude": ["f001"], "hard_distractors": ["f001", "f003"], "should_include": [], "expected_current": ["f002"], "answer_type": "factual", "adversarial_notes": "Must ignore bookstore-charm noise and retrieve the current app."},
        ]),
    ]


def main() -> int:
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    QUERIES_DIR.mkdir(parents=True, exist_ok=True)
    personas = build_personas()
    queries = build_queries()
    for persona in personas:
        _write_json(PERSONAS_DIR / f"{persona['persona_id']}.json", persona)
    for query_set in queries:
        suffix = query_set["persona_id"].split("_", 1)[1]
        _write_json(QUERIES_DIR / f"queries_{suffix}.json", query_set)
    print(f"Generated {len(personas)} personas and {len(queries)} query files under ~/.akashik/data/benchmarks/acmb/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
