"""Calibração única: regras visuais e matriz compartilham o limiar."""
PARAMETERS = {
    "confidence_threshold": .60,
    "foreground_delta": 28,
    "contact_gap_px": 10,
    "candidate_gap_px": 25,
    "min_approach_px_s": 12,
    "history_seconds": .55,
    "post_contact_seconds": 1.45,
    "post_speed_ratio": .55,
    "dedup_seconds": 8,
    "dedup_radius_px": 140,
    "lane_bounds_px": [[65, 120], [120, 175], [175, 230], [230, 285]],
    "weights": {"approach": .20, "contact": .20, "deceleration": .25,
                "immobility": .15, "category_margin": .20},
}
