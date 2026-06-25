from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt


# -----------------------------
# Paths
# -----------------------------
RESULTS_FILE = Path(r"C:\vpn-thesis\analysis\outputs\results.csv")
FIG_DIR = Path(r"C:\vpn-thesis\analysis\figures_boxplots")
FIG_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Style
# -----------------------------
sns.set_theme(style="whitegrid", context="talk")
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["ps.fonttype"] = 42

VPN_ORDER = ["wireguard", "openvpn", "ipsec"]
CLIENT_ORDER = ["VM", "WSL", "RaspberryPi"]
BAND_ORDER = ["5GHz", "2.4GHz"]


# -----------------------------
# Load data
# -----------------------------
df = pd.read_csv(RESULTS_FILE)
df.columns = [c.strip() for c in df.columns]

# Normalize useful columns
numeric_cols = [
    "tcp_throughput_mbps",
    "udp_throughput_mbps",
    "rtt_min_ms",
    "rtt_avg_ms",
    "rtt_max_ms",
    "rtt_mdev_ms",
    "cpu_avg_percent",
    "cpu_max_percent",
    "reconnect_ms",
    "handshake_ms",
    "throughput_per_cpu",
    "delay_ms",
    "loss_pct",
    "mtu",
]
for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")


def normalize_band(value) -> str:
    s = str(value).strip().lower().replace(" ", "")
    if s in {"", "none", "nan", "unknown"}:
        return "unknown"
    if "2.4" in s or "24ghz" in s:
        return "2.4GHz"
    if "5ghz" in s or s == "5g":
        return "5GHz"
    return str(value).strip()


if "wifi_band" in df.columns:
    df["wifi_band"] = df["wifi_band"].apply(normalize_band)
else:
    df["wifi_band"] = "unknown"

# Make sure client_type exists even if older CSVs are used
if "client_type" not in df.columns:
    if "client_role" in df.columns:
        def _client_from_role(v):
            s = str(v).strip().lower()
            if s == "vm":
                return "VM"
            if s == "wsl":
                return "WSL"
            if s in {"pi", "raspberrypi", "raspberry pi"}:
                return "RaspberryPi"
            return "Unknown"
        df["client_type"] = df["client_role"].apply(_client_from_role)
    else:
        df["client_type"] = "Unknown"


# -----------------------------
# Helpers
# -----------------------------
def save_boxplot_with_values(
    data: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    filename: str,
    ylabel: str | None = None,
    order: list[str] | None = None,
    hue: str | None = None,
    hue_order: list[str] | None = None,
    decimals: int = 2,
):
    plot_data = data.copy()

    fig, ax = plt.subplots(figsize=(11, 6.5))

    sns.boxplot(
        data=plot_data,
        x=x,
        y=y,
        hue=hue,
        order=order,
        hue_order=hue_order,
        showfliers=True,
        whis=1.5,
        width=0.6,
        ax=ax,
    )

    sns.stripplot(
        data=plot_data,
        x=x,
        y=y,
        hue=hue,
        order=order,
        hue_order=hue_order,
        dodge=bool(hue),
        jitter=0.18,
        color="black",
        size=3.3,
        alpha=0.45,
        ax=ax,
    )

    # Remove duplicate legend and rebuild clean one
    if hue:
        handles, labels = ax.get_legend_handles_labels()
        if hue_order is None:
            hue_labels = list(pd.unique(plot_data[hue].dropna()))
        else:
            hue_labels = hue_order
        ax.legend(handles[: len(hue_labels)], hue_labels, title=hue, frameon=False)
    else:
        leg = ax.get_legend()
        if leg:
            leg.remove()

    # Median labels
    if order is None:
        x_levels = list(pd.unique(plot_data[x].dropna()))
    else:
        x_levels = order

    if hue:
        if hue_order is None:
            h_levels = list(pd.unique(plot_data[hue].dropna()))
        else:
            h_levels = hue_order

        if len(h_levels) == 1:
            offsets = [0.0]
        else:
            offsets = np.linspace(-0.22, 0.22, len(h_levels))

        for xi, xv in enumerate(x_levels):
            for hi, hv in enumerate(h_levels):
                sub = plot_data[(plot_data[x] == xv) & (plot_data[hue] == hv)][y].dropna()
                if sub.empty:
                    continue
                med = sub.median()
                ax.text(
                    xi + offsets[hi],
                    med,
                    f"{med:.{decimals}f}",
                    ha="center",
                    va="bottom",
                    fontsize=8.5,
                    fontweight="bold",
                )
    else:
        for xi, xv in enumerate(x_levels):
            sub = plot_data[plot_data[x] == xv][y].dropna()
            if sub.empty:
                continue
            med = sub.median()
            ax.text(
                xi,
                med,
                f"{med:.{decimals}f}",
                ha="center",
                va="bottom",
                fontsize=8.5,
                fontweight="bold",
            )

    ax.set_title(title, pad=14)
    ax.set_xlabel("")
    ax.set_ylabel(ylabel if ylabel else y)
    ax.grid(axis="y", alpha=0.25)

    plt.tight_layout()
    out = FIG_DIR / f"{filename}.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def stage_subset(stage: str, band: str = "5GHz") -> pd.DataFrame:
    s = df[df["stage"] == stage].copy()

    # Main results: focus on 5 GHz if available
    if band != "all" and "wifi_band" in s.columns:
        band_subset = s[s["wifi_band"] == band].copy()
        if not band_subset.empty:
            s = band_subset

    s["vpn"] = pd.Categorical(s["vpn"], categories=VPN_ORDER, ordered=True)
    s["client_type"] = pd.Categorical(s["client_type"], categories=CLIENT_ORDER, ordered=True)
    return s.sort_values(["client_type", "vpn"])


def plot_stage_metric(
    stage: str,
    metric: str,
    title: str,
    filename: str,
    ylabel: str,
    decimals: int = 2,
    band: str = "5GHz",
):
    s = stage_subset(stage, band=band)
    if s.empty or metric not in s.columns or s[metric].dropna().empty:
        return None

    return save_boxplot_with_values(
        data=s,
        x="vpn",
        y=metric,
        title=title,
        filename=filename,
        ylabel=ylabel,
        order=VPN_ORDER,
        hue="client_type" if "client_type" in s.columns else None,
        hue_order=CLIENT_ORDER if "client_type" in s.columns else None,
        decimals=decimals,
    )


def plot_band_comparison_for_client(client_type: str):
    s = df[(df["stage"] == "baseline") & (df["client_type"] == client_type)].copy()
    s = s[s["wifi_band"].isin(BAND_ORDER)]

    if s.empty or "tcp_throughput_mbps" not in s.columns or s["tcp_throughput_mbps"].dropna().empty:
        return None

    s["wifi_band"] = pd.Categorical(s["wifi_band"], categories=BAND_ORDER, ordered=True)
    s["vpn"] = pd.Categorical(s["vpn"], categories=VPN_ORDER, ordered=True)

    return save_boxplot_with_values(
        data=s,
        x="wifi_band",
        y="tcp_throughput_mbps",
        title=f"Baseline throughput: 5 GHz vs 2.4 GHz ({client_type})",
        filename=f"band_comparison_throughput_{client_type.lower()}",
        ylabel="Throughput (Mbps)",
        order=BAND_ORDER,
        hue="vpn",
        hue_order=VPN_ORDER,
        decimals=2,
    )


# -----------------------------
# Main figure set
# -----------------------------
generated = []

# Baseline
generated.append(plot_stage_metric("baseline", "tcp_throughput_mbps", "Baseline TCP throughput", "baseline_throughput", "Throughput (Mbps)", band="5GHz"))
generated.append(plot_stage_metric("baseline", "rtt_avg_ms", "Baseline RTT", "baseline_rtt", "RTT (ms)", band="5GHz"))
generated.append(plot_stage_metric("baseline", "cpu_avg_percent", "Baseline CPU usage", "baseline_cpu", "CPU (%)", band="5GHz"))
generated.append(plot_stage_metric("baseline", "throughput_per_cpu", "Throughput per CPU efficiency", "baseline_efficiency", "Mbps per %CPU", decimals=1, band="5GHz"))
generated.append(plot_stage_metric("baseline", "rtt_mdev_ms", "Baseline jitter", "baseline_jitter", "Jitter (ms)", band="5GHz"))

# Latency
generated.append(plot_stage_metric("latency", "tcp_throughput_mbps", "Throughput under 50 ms latency", "latency_throughput", "Throughput (Mbps)", band="5GHz"))
generated.append(plot_stage_metric("latency", "rtt_avg_ms", "RTT under 50 ms latency", "latency_rtt", "RTT (ms)", band="5GHz"))
generated.append(plot_stage_metric("latency", "rtt_mdev_ms", "Jitter under 50 ms latency", "latency_jitter", "Jitter (ms)", band="5GHz"))

# Loss
generated.append(plot_stage_metric("loss", "tcp_throughput_mbps", "Throughput under 1% packet loss", "loss_throughput", "Throughput (Mbps)", band="5GHz"))
generated.append(plot_stage_metric("loss", "rtt_avg_ms", "RTT under 1% packet loss", "loss_rtt", "RTT (ms)", band="5GHz"))
generated.append(plot_stage_metric("loss", "rtt_mdev_ms", "Jitter under 1% packet loss", "loss_jitter", "Jitter (ms)", band="5GHz"))

# MTU
generated.append(plot_stage_metric("mtu", "tcp_throughput_mbps", "Throughput with MTU 1400", "mtu_throughput", "Throughput (Mbps)", band="5GHz"))

# CPU stress
generated.append(plot_stage_metric("cpu_stress", "tcp_throughput_mbps", "Throughput under CPU stress", "cpu_stress_throughput", "Throughput (Mbps)", band="5GHz"))
generated.append(plot_stage_metric("cpu_stress", "cpu_avg_percent", "CPU usage under stress", "cpu_stress_cpu", "CPU (%)", band="5GHz"))

# Mobility
generated.append(plot_stage_metric("mobility", "reconnect_ms", "Reconnect time in mobility stage", "mobility_reconnect", "Reconnect time (ms)", decimals=0, band="5GHz"))
generated.append(plot_stage_metric("mobility", "handshake_ms", "Handshake time in mobility stage", "mobility_handshake", "Handshake time (ms)", decimals=0, band="5GHz"))

# Band comparison figures for baseline throughput
generated.append(plot_band_comparison_for_client("VM"))
generated.append(plot_band_comparison_for_client("WSL"))
generated.append(plot_band_comparison_for_client("RaspberryPi"))

print(f"Saved figures to: {FIG_DIR}")
print(f"Figures generated: {len([p for p in generated if p is not None])}")