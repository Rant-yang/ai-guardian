"""Validate a decision completely before trusting its mode or permission fields."""
import re


def validate_decision(value):
    if not isinstance(value,dict):raise ValueError('Invalid decision object')
    if value.get('mode') not in ('observe','protect'):raise ValueError('Invalid decision mode')
    if value.get('verdict') not in ('pass','warn','review','deny'):raise ValueError('Invalid verdict')
    findings=value.get('findings')
    if not isinstance(findings,list) or len(findings)>64 or any(
        not isinstance(item,str) or not re.fullmatch(r'[a-z0-9_:-]{1,120}',item) for item in findings
    ):raise ValueError('Invalid findings')
    return value
