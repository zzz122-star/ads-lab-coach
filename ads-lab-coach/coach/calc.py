import math

C0 = 299792458.0


def microstrip_width(z0: float, er: float, h: float) -> float:
    a = z0 / 60.0 * math.sqrt((er + 1) / 2) + (er - 1) / (er + 1) * (0.23 + 0.11 / er)
    w_narrow = 8 * math.exp(a) / (math.exp(2 * a) - 2)
    if w_narrow < 2:
        return w_narrow * h
    b = 377 * math.pi / (2 * z0 * math.sqrt(er))
    w_wide = (2 / math.pi) * (
        b - 1 - math.log(2 * b - 1)
        + (er - 1) / (2 * er) * (math.log(b - 1) + 0.39 - 0.61 / er)
    )
    return w_wide * h


def microstrip_eeff(w: float, er: float, h: float) -> float:
    u = w / h
    base = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** -0.5
    if u < 1:
        base += (er - 1) / 2 * 0.04 * (1 - u) ** 2
    return base


def microstrip_z0(w: float, er: float, h: float) -> float:
    u = w / h
    ee = microstrip_eeff(w, er, h)
    if u <= 1:
        return 60 / math.sqrt(ee) * math.log(8 / u + u / 4)
    return 120 * math.pi / (math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444)))


def guided_wavelength(f_hz: float, eeff: float) -> float:
    return C0 / (f_hz * math.sqrt(eeff))


def free_space_wavelength(f_hz: float) -> float:
    return C0 / f_hz


def quarter_wave_len(z0: float, er: float, h: float, f_ghz: float) -> float:
    """微带线的四分之一导波波长，单位 mm。"""
    w = microstrip_width(z0, er, h)
    ee = microstrip_eeff(w, er, h)
    return guided_wavelength(f_ghz * 1e9, ee) * 1e3 / 4


def reflection_coeff(zl: float, z0: float) -> float:
    return abs((zl - z0) / (zl + z0))


def vswr(zl: float, z0: float) -> float:
    g = reflection_coeff(zl, z0)
    return (1 + g) / (1 - g)


def return_loss_db(zl: float, z0: float) -> float:
    return -20 * math.log10(reflection_coeff(zl, z0))


def db_to_mag(db: float) -> float:
    return 10 ** (db / 20)


def _eeff_of(p: dict, z: float) -> float:
    w = microstrip_width(z, p["er"], p["h_mm"])
    return microstrip_eeff(w, p["er"], p["h_mm"])


METRICS = {
    "microstrip_width": lambda p: microstrip_width(p["z0"], p["er"], p["h_mm"]),
    "microstrip_eeff": lambda p: _eeff_of(p, p["z0"]),
    "guided_wavelength_mm": lambda p: guided_wavelength(p["f0_ghz"] * 1e9, _eeff_of(p, p["z0"])) * 1e3,
    "free_space_wavelength_mm": lambda p: free_space_wavelength(p["f0_ghz"] * 1e9) * 1e3,
    "quarter_wave_len_mm": lambda p: quarter_wave_len(p["z0"], p["er"], p["h_mm"], p["f0_ghz"]),
    "vswr": lambda p: vswr(p["zl"], p["z0"]),
    "return_loss_db": lambda p: return_loss_db(p["zl"], p["z0"]),
    "low_width": lambda p: microstrip_width(p["z_low"], p["er"], p["h_mm"]),
    "high_width": lambda p: microstrip_width(p["z_high"], p["er"], p["h_mm"]),
    "low_eighth_len": lambda p: quarter_wave_len(p["z_low"], p["er"], p["h_mm"], p["fc_ghz"]) / 2,
    "high_eighth_len": lambda p: quarter_wave_len(p["z_high"], p["er"], p["h_mm"], p["fc_ghz"]) / 2,
    "arm_impedance": lambda p: math.sqrt(2) * p["z0"],
    "isolation_resistor": lambda p: 2 * p["z0"],
    "arm_width": lambda p: microstrip_width(math.sqrt(2) * p["z0"], p["er"], p["h_mm"]),
    "arm_quarter_len": lambda p: quarter_wave_len(math.sqrt(2) * p["z0"], p["er"], p["h_mm"], p["f0_ghz"]),
}


def metric(name: str, params: dict) -> float:
    try:
        fn = METRICS[name]
    except KeyError as exc:
        raise KeyError(f"未注册的计算指标: {name}") from exc
    return fn(params)
