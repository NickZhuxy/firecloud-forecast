"""Figure 1: Spectral extinction at sunset (SZA = 90°).

Plots Rayleigh, Mie (clean troposphere), and ozone Chappuis contributions
to total optical depth across the visible spectrum, plus the resulting
transmission $T = e^{-\\tau_{total}}$.

Approximations used (illustrative, not for quantitative reference):
- Rayleigh: standard atmosphere zenith formula (Bodhaine et al. 1999 form),
  scaled by Kasten-Young air mass m = 38 at SZA = 90°.
- Mie: clean-atmosphere wavelength-independent zenith AOD = 0.05.
- Ozone Chappuis: Gaussian approximation centered 600 nm with peak
  sigma = 5e-21 cm²/molecule (consistent with Brion et al. 1998 measurements);
  total ozone column 300 DU.

Usage: uv run python docs/paper/figures/fig1_extinction_spectrum.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def main() -> None:
    lam_nm = np.linspace(400, 700, 301)
    lam_um = lam_nm / 1000.0

    m_sza90 = 38.0  # Kasten-Young air mass at SZA = 90°

    # Rayleigh: Bodhaine-form approximation at zenith, scaled by air mass.
    tau_R = 0.008569 * lam_um ** -4 * (1 + 0.0113 * lam_um ** -2) * m_sza90

    # Mie (clean troposphere): wavelength-independent at this approximation level.
    tau_Mie = np.full_like(lam_nm, 0.05 * m_sza90)

    # Ozone Chappuis: Gaussian approximation; cross-section ~5e-21 at 600 nm.
    sigma_O3 = 5e-21 * np.exp(-((lam_nm - 600.0) / 60.0) ** 2)
    N_O3 = 300.0 * 2.687e16  # 300 DU in molecules/cm^2
    tau_O3 = sigma_O3 * N_O3 * m_sza90

    tau_total = tau_R + tau_Mie + tau_O3
    transmission = np.exp(-tau_total)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 7.5), sharex=True)

    ax1.plot(lam_nm, tau_R, color="#3457D5", linewidth=2.0, label="Rayleigh")
    ax1.plot(lam_nm, tau_Mie, color="#6B8E23", linewidth=2.0, linestyle="--", label="Mie (clean troposphere, AOD₀ = 0.05)")
    ax1.plot(lam_nm, tau_O3, color="#C0392B", linewidth=2.0, linestyle=":", label="Ozone Chappuis (300 DU)")
    ax1.plot(lam_nm, tau_total, color="black", linewidth=2.8, label="Total")
    ax1.set_ylabel(r"Optical depth $\tau$ at SZA = 90°")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.set_title("(a) Wavelength-resolved contributions to total optical depth")

    ax2.plot(lam_nm, transmission, color="black", linewidth=2.0)
    ax2.fill_between(lam_nm, 0, transmission, color="black", alpha=0.15)
    ax2.set_xlabel("Wavelength (nm)")
    ax2.set_ylabel(r"Transmission $T = e^{-\tau_{\rm total}}$")
    ax2.set_xlim(400, 700)
    ax2.set_ylim(0, max(transmission) * 1.1)
    ax2.grid(True, alpha=0.3)
    ax2.set_title("(b) Surviving spectrum reaching a cloud at altitude (illustrative)")

    # Color band strip beneath panel (b)
    for nm in np.arange(400, 700, 4):
        if nm < 440:
            color = (0.5, 0.0, 1.0)
        elif nm < 490:
            color = (0.0, 0.0, 1.0)
        elif nm < 510:
            color = (0.0, 1.0, 1.0)
        elif nm < 580:
            color = (0.0, 1.0, 0.0)
        elif nm < 645:
            color = (1.0, 1.0, 0.0)
        elif nm < 680:
            color = (1.0, 0.5, 0.0)
        else:
            color = (1.0, 0.0, 0.0)
        ax2.axvspan(nm, nm + 4, ymin=0.0, ymax=0.04, color=color, alpha=0.85)

    fig.suptitle("Figure 1. Spectral extinction at apparent sunset (SZA = 90°)", y=1.0)
    fig.tight_layout()

    out = Path(__file__).parent / "fig1_extinction_spectrum.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
