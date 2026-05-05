import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from datetime import datetime

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def print_header(mode: str):
    mode_color = "green" if mode == "auto" else "yellow"
    console.print(Panel(
        f"[bold white]Trader Agent[/bold white]  "
        f"[{mode_color}]● {mode.upper()}[/{mode_color}]  "
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]",
        box=box.SIMPLE_HEAD,
        style="dim",
    ))


def print_signals(signals: list[dict]):
    if not signals:
        console.print("[dim]  No signals above threshold right now.[/dim]\n")
        return

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold dim",
        padding=(0, 1),
    )
    table.add_column("Ticker", style="bold white", width=8)
    table.add_column("Signal", width=9)
    table.add_column("Z", justify="right", width=7)
    table.add_column("RSI", justify="right", width=7)
    table.add_column("Price", justify="right", width=9)
    table.add_column("Entry", justify="right", width=9)
    table.add_column("Stop", justify="right", width=9)
    table.add_column("Target", justify="right", width=9)
    table.add_column("Size", justify="right", width=8)
    table.add_column("Conf", justify="right", width=7)

    for s in signals:
        direction = s["direction"]
        sig_color = "green" if direction == "LONG" else "red"
        conf = s["confidence"]
        conf_color = "green" if conf >= 75 else "yellow" if conf >= 60 else "dim"

        table.add_row(
            s["ticker"],
            f"[{sig_color}]{direction}[/{sig_color}]",
            f"{s['zscore']:.2f}",
            f"{s['rsi']:.1f}",
            f"${s['price']:.2f}",
            f"${s['entry']:.2f}",
            f"[red]${s['stop']:.2f}[/red]",
            f"[green]${s['target']:.2f}[/green]",
            f"{s['shares']}sh",
            f"[{conf_color}]{conf:.0f}[/{conf_color}]",
        )

    console.print(table)


def print_portfolio(portfolio: dict):
    cap = portfolio.get("capital", 0)
    peak = portfolio.get("peak_capital", cap)
    dd = (peak - cap) / peak * 100 if peak > 0 else 0
    positions = portfolio.get("positions", {})

    dd_color = "red" if dd > 5 else "yellow" if dd > 2 else "green"
    console.print(
        f"  [dim]Capital[/dim] [white]${cap:,.0f}[/white]  "
        f"[dim]Drawdown[/dim] [{dd_color}]{dd:.2f}%[/{dd_color}]  "
        f"[dim]Positions[/dim] [white]{len(positions)}[/white]\n"
    )


def print_skipped(skipped: list[tuple[str, str]]):
    if not skipped:
        return
    parts = ", ".join(f"[dim]{t}[/dim] [dim italic]({r})[/dim italic]" for t, r in skipped)
    console.print(f"  Skipped: {parts}\n")


def print_execution(ticker: str, action: str, shares: int, price: float, mode: str):
    color = "green" if action == "BUY" else "red"
    tag = "[AUTO]" if mode == "auto" else "[SUGGEST]"
    console.print(
        f"  [{color}]{tag} {action} {shares}sh {ticker} @ ${price:.2f}[/{color}]"
    )