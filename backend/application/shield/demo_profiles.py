"""Pure, deterministic synthetic supplier samples; no ORM or database writes.

These profiles describe simulated data, not real manufacturers or measured
performance. A caller must reuse the OLD installation's profile for removal
wear and repairs, and preserve the existing installation/removal identity chain.
"""
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import math


PROFILES = (
    {'name': '模拟厂家01·磐岳', 'brand': '磐岳（模拟）', 'disc_price': 5600, 'scraper_price': 1600, 'normal_probability': 0.74},
    {'name': '模拟厂家02·青岚', 'brand': '青岚（模拟）', 'disc_price': 6050, 'scraper_price': 1840, 'normal_probability': 0.62},
    {'name': '模拟厂家03·砺川', 'brand': '砺川（模拟）', 'disc_price': 6420, 'scraper_price': 2080, 'normal_probability': 0.80},
    {'name': '模拟厂家04·衡峰', 'brand': '衡峰（模拟）', 'disc_price': 6870, 'scraper_price': 2330, 'normal_probability': 0.54},
    {'name': '模拟厂家05·远砧', 'brand': '远砧（模拟）', 'disc_price': 7280, 'scraper_price': 2580, 'normal_probability': 0.69},
    {'name': '模拟厂家06·澄岩', 'brand': '澄岩（模拟）', 'disc_price': 7720, 'scraper_price': 2810, 'normal_probability': 0.46},
    {'name': '模拟厂家07·峻泽', 'brand': '峻泽（模拟）', 'disc_price': 8130, 'scraper_price': 3060, 'normal_probability': 0.77},
    {'name': '模拟厂家08·砺航', 'brand': '砺航（模拟）', 'disc_price': 8500, 'scraper_price': 3300, 'normal_probability': 0.58},
)


def _unit(channel, *keys):
    # Separate hash channels keep price, vendor and wear draws independent;
    # unlike Python hash(), this is stable across processes and environments.
    payload = json.dumps(['shield-demo-profiles-v1', channel, *keys],
                         ensure_ascii=False, sort_keys=True, default=str, separators=(',', ':'))
    return int.from_bytes(sha256(payload.encode('utf-8')).digest()[:8], 'big') / 2**64


def _nonnegative(value, name):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f'{name} must be finite and non-negative')
    return number


def _base(profile, parent_type):
    if parent_type not in {'DISC', 'SCRAPER'}:
        raise ValueError('parent_type must be DISC or SCRAPER')
    return float(profile['disc_price' if parent_type == 'DISC' else 'scraper_price'])


def _money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def profile_for(key, service_rings=None):
    """Choose a fresh profile dict; optionally stratify EXISTING service spans.

    Overlapping weights and a uniform floor keep all eight suppliers possible.
    This can illustrate different group means without changing any chain or
    claiming that synthetic supplier labels caused the observed service spans.
    """
    weights = [1.0] * len(PROFILES)
    if service_rings is not None:
        span = _nonnegative(service_rings, 'service_rings')
        centers = (26, 36, 46, 58, 75, 95, 125, 165)
        weights = [0.16 + math.exp(-0.5 * ((math.log1p(span) - math.log1p(center)) / 0.30) ** 2)
                   for center in centers]
    target = _unit('profile', key) * sum(weights)
    for profile, weight in zip(PROFILES, weights):
        target -= weight
        if target < 0:
            return dict(profile)
    return dict(PROFILES[-1])


def installation_price(profile, parent_type, key, ring):
    """Decimal registration price with supplier drift, period variation and noise."""
    base = _base(profile, parent_type)
    ring = _nonnegative(ring, 'ring')
    name = profile['name']
    # Independently hashed period anchors interpolate smoothly, without a
    # repeating modulo cycle synchronizing vendors and replacement positions.
    period = math.floor(ring / 100)
    progress = ring / 100 - period
    left = _unit('period-price', name, parent_type, period)
    right = _unit('period-price', name, parent_type, period + 1)
    market = (left * (1 - progress) + right * progress - 0.5) * 0.08
    drift = (_unit('price-drift', name, parent_type) - 0.4) * 0.14 * ring / (ring + 400)
    jitter = (_unit('price-a', name, parent_type, key, ring)
              + _unit('price-b', name, parent_type, key, ring) - 1) * 0.11
    return _money(base * (1 + market + drift + jitter))


def wear_values(profile, parent_type, key, ring, checked_only=False):
    """Return flat detail/old-record wear fields; caller selects model fields.

    Detail fields: wear_condition, blade_wear_amount, repair_parts.
    Other fields belong to OldToolRecord; wear_condition/repair_parts are shared.
    No identity, inspection status, workflow state or timestamps are generated.
    Pass the same profile/key/ring to repair_price for matching repair amounts.
    """
    _base(profile, parent_type)
    ring = _nonnegative(ring, 'ring')
    name = profile['name']
    probability = float(profile['normal_probability'])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('normal_probability must be between zero and one')
    probability += (_unit('wear-period', name, math.floor(ring / 100)) - 0.5) * 0.04
    probability = min(0.94, probability + 0.14) if checked_only else probability
    normal = _unit('wear-state', name, parent_type, key, ring) < probability
    choices = ('中度磨损', '偏磨') if checked_only else (
        ('中度磨损', '偏磨', '严重磨损', '刀圈崩刃', '轴承损坏', '断裂', '刀圈脱落')
        if parent_type == 'DISC' else ('中度磨损', '偏磨', '严重磨损', '崩刃', '断裂', '脱落'))
    condition = '正常' if normal else choices[min(int(_unit('wear-kind', name, parent_type, key, ring) * len(choices)), len(choices) - 1)]
    amount_draw = _unit('wear-amount', name, parent_type, key, ring)
    low, high = (0.3, 2.2) if normal else (2.3, 6.5) if checked_only else (5.0, 13.0)
    if condition == '严重磨损':
        low, high = 14.0, 23.0
    amount = round((low + (high - low) * amount_draw) * (1.2 if parent_type == 'SCRAPER' else 1), 2)
    disc = parent_type == 'DISC'
    values = {
        'wear_condition': condition, 'blade_wear_amount': amount,
        'ring_wear_amount': amount if disc else None,
        'bias_wear_amount': round(0.7 + amount_draw * 1.8, 2) if disc and condition == '偏磨' else 0.0 if disc else None,
        'ring_damage': [], 'ring_tooth_loss_count': 0 if disc else None,
        'ring_other_condition': None, 'bearing_failed': False if disc else None,
        'bearing_failure_reasons': [], 'bearing_other_condition': None,
        'hub_damaged': False if disc else None, 'hub_failure_reasons': [], 'hub_other_condition': None,
        'scraper_wear_amount': None if disc else amount,
        'scraper_chipped': None if disc else False, 'scraper_broken': None if disc else False,
        'scraper_detached': None if disc else False,
        'repair_parts': [], 'repair_result': '模拟：复检正常，无维修项目',
    }
    if normal:
        return values
    values['repair_parts'] = ['刀圈'] if disc else ['刮刀刀体']
    values['repair_result'] = '模拟：修复刀圈磨损' if disc else '模拟：堆焊修复刮刀刃口'
    if disc and condition == '刀圈崩刃':
        values.update(ring_damage=['CHIP'], ring_other_condition='模拟：刀圈局部崩刃', repair_result='模拟：更换崩刃刀圈')
    elif disc and condition == '轴承损坏':
        values.update(bearing_failed=True, bearing_failure_reasons=['FATIGUE_DAMAGE'],
                      bearing_other_condition='模拟：轴承疲劳损伤，转动不畅', repair_parts=['轴承'], repair_result='模拟：更换轴承')
    elif disc and condition == '刀圈脱落':
        values.update(ring_damage=['BOLT_LOSS'], ring_other_condition='模拟：紧固件松脱导致刀圈脱落',
                      repair_parts=['刀圈', '紧固件'], repair_result='模拟：更换刀圈及紧固件')
    elif disc and condition == '断裂':
        values.update(ring_damage=['FRACTURE'], ring_other_condition='模拟：刀圈断裂',
                      repair_parts=[], repair_result='模拟：断裂待处置复核，暂无维修项目')
    elif not disc and condition in {'崩刃', '断裂', '脱落'}:
        field = {'崩刃': 'scraper_chipped', '断裂': 'scraper_broken', '脱落': 'scraper_detached'}[condition]
        values[field] = True
        if condition in {'断裂', '脱落'}:
            values.update(repair_parts=[], repair_result=f'模拟：刮刀{condition}待处置复核，暂无维修项目')
    return values


def repair_price(profile, parent_type, key, ring):
    """Decimal repair quote consistent with wear_values for the same inputs."""
    wear = wear_values(profile, parent_type, key, ring)
    if wear['wear_condition'] in {'正常', '断裂', '脱落'}:
        return Decimal('0.00')
    base = installation_price(profile, parent_type, key, ring)
    fraction = 0.16 + _unit('repair-fraction', profile['name'], parent_type, key, ring) * 0.22
    if wear['wear_condition'] in {'轴承损坏', '刀圈脱落'}:
        fraction += 0.06
    return _money(base * Decimal(str(fraction)))
