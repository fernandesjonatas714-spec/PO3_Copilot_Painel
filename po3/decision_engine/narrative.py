from __future__ import annotations
from .prompts import build_narrative_prompt

def generate_narrative(send_detailed, state, decisions, gate, consensus, model):
    result=send_detailed(build_narrative_prompt(state.to_dict(), [x.to_dict() for x in decisions], gate.to_dict(), consensus, model))
    return result