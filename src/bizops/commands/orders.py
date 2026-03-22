"""Smart ordering commands — generate, manage, and export purchase orders."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console

from bizops.utils.config import ProductItem, load_config, save_config
from bizops.utils.display import (
    create_budget_panel,
    create_order_table,
    create_product_catalog_table,
    get_spinner,
    print_error,
    print_info,
    print_success,
    print_warning,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    today = "today"
    week = "week"
    month = "month"
    quarter = "quarter"


def _resolve_date_range(period: TimeRange) -> tuple[str, str]:
    today = datetime.now()
    if period == TimeRange.today:
        d = today.strftime("%Y-%m-%d")
        return d, d
    elif period == TimeRange.week:
        start = today - timedelta(days=today.weekday())
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == TimeRange.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.command("catalog")
def catalog(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name."),
) -> None:
    """List products in a vendor's catalog."""
    config = load_config()
    vendor_lower = vendor.lower()

    for vc in config.vendors:
        if vc.name.lower() == vendor_lower or any(
            a.lower() == vendor_lower for a in vc.aliases
        ):
            if not vc.products:
                print_warning(f"No products configured for {vc.name}. Use 'bizops orders add-product' to add.")
                return
            console.print(create_product_catalog_table(vc.name, vc.products))
            print_info(f"{len(vc.products)} products in catalog")
            return

    print_error(f"Vendor '{vendor}' not found in config.")


@app.command("add-product")
def add_product(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name."),
    name: str = typer.Option(..., "--name", "-n", help="Product name."),
    unit: str = typer.Option("each", "--unit", "-u", help="Unit (case, lb, bag, bunch)."),
    cost: float = typer.Option(0.0, "--cost", "-c", help="Cost per unit."),
    par: float = typer.Option(0.0, "--par", "-p", help="Par level (minimum to keep)."),
    multiple: float = typer.Option(1.0, "--multiple", "-m", help="Order multiple."),
    category: str = typer.Option("food_supplies", "--category", help="Expense category."),
    sku: str = typer.Option("", "--sku", help="Vendor SKU/item code."),
) -> None:
    """Add a product to a vendor's catalog."""
    config = load_config()
    vendor_lower = vendor.lower()

    for vc in config.vendors:
        if vc.name.lower() == vendor_lower or any(
            a.lower() == vendor_lower for a in vc.aliases
        ):
            product = ProductItem(
                name=name,
                sku=sku,
                unit=unit,
                unit_cost=cost,
                par_level=par,
                order_multiple=multiple,
                category=category,
            )
            vc.products.append(product)
            save_config(config)
            print_success(f"Added '{name}' to {vc.name}'s catalog")
            print_info(f"  Unit: {unit} | Cost: ${cost:.2f} | Par: {par:g} | Multiple: {multiple:g}")
            return

    print_error(f"Vendor '{vendor}' not found. Add the vendor to config first.")


@app.command("scan-emails")
def scan_emails(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name to scan for."),
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Time period to scan."
    ),
    save: bool = typer.Option(
        False, "--save", "-s", help="Auto-save discovered products to vendor catalog."
    ),
) -> None:
    """Scan Gmail emails to discover products from a vendor.

    Extracts product names, quantities, and prices from order/invoice emails.
    """
    from bizops.parsers.product_extractor import ProductExtractor
    from bizops.utils.storage import load_invoices

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task(f"Scanning emails for {vendor} products...", total=None)

        invoices = load_invoices(config, start, end)
        if not invoices:
            print_warning("No invoice data found. Run 'bizops invoices pull' first.")
            raise typer.Exit(0)

        extractor = ProductExtractor(config)
        extracted = extractor.extract_from_emails(invoices, vendor)

    if not extracted:
        print_warning(f"No product details found in emails from {vendor}.")
        print_info("Try uploading a product list with 'bizops orders import-catalog'.")
        raise typer.Exit(0)

    # Display what we found
    from rich.table import Table

    table = Table(title=f"Products found from {vendor}", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Product", style="cyan", width=25)
    table.add_column("Unit", width=8)
    table.add_column("Cost", justify="right", width=10)
    table.add_column("Last Qty", justify="right", width=10)
    table.add_column("Source Date", width=12)

    for i, item in enumerate(extracted, 1):
        table.add_row(
            str(i),
            item.get("name", ""),
            item.get("unit", "each"),
            f"${item.get('unit_cost', 0):,.2f}" if item.get("unit_cost") else "--",
            f"{item.get('quantity', 0):g}" if item.get("quantity") else "--",
            item.get("source_date", ""),
        )

    console.print(table)
    print_info(f"Found {len(extracted)} products from {vendor}")

    if save:
        # Convert to ProductItems and save to vendor config
        product_items = extractor.to_product_items(extracted)
        vendor_lower = vendor.lower()

        for vc in config.vendors:
            if vc.name.lower() == vendor_lower or any(
                a.lower() == vendor_lower for a in vc.aliases
            ):
                existing_names = {p.name.lower() for p in vc.products}
                added = 0
                for pi in product_items:
                    if pi.name.lower() not in existing_names:
                        vc.products.append(pi)
                        existing_names.add(pi.name.lower())
                        added += 1

                save_config(config)
                print_success(f"Added {added} new products to {vc.name}'s catalog")
                if len(product_items) - added > 0:
                    print_info(f"  Skipped {len(product_items) - added} already in catalog")
                return

        print_error(f"Vendor '{vendor}' not found in config. Add vendor first.")


@app.command("import-catalog")
def import_catalog(
    file: Path = typer.Option(
        ..., "--file", "-f", help="Path to CSV or Excel file.", exists=True,
    ),
    vendor: str = typer.Option(
        "", "--vendor", "-v", help="Vendor name (if not in file).",
    ),
) -> None:
    """Import product catalog from a CSV or Excel file.

    Expected columns: name (required), unit, cost, par, multiple, category, sku.
    """
    from bizops.parsers.product_extractor import ProductExtractor

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task(f"Importing products from {file.name}...", total=None)

        extractor = ProductExtractor(config)
        try:
            extracted = extractor.import_from_file(file)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)

    if not extracted:
        print_warning(f"No products found in {file.name}.")
        raise typer.Exit(0)

    # Group by vendor if vendor column exists
    by_vendor: dict[str, list[dict]] = {}
    for item in extracted:
        v = item.get("vendor") or vendor
        if not v:
            v = "unassigned"
        by_vendor.setdefault(v, []).append(item)

    total_added = 0

    for v_name, items in by_vendor.items():
        product_items = extractor.to_product_items(
            items,
            default_category=items[0].get("category", "food_supplies"),
        )

        if v_name == "unassigned":
            # Display but don't save without vendor
            console.print(create_product_catalog_table(f"Unassigned ({file.name})", product_items))
            print_warning(
                f"{len(product_items)} products have no vendor. "
                "Use --vendor flag or add 'vendor' column to file."
            )
            continue

        # Find vendor in config
        vendor_lower = v_name.lower()
        vendor_found = False
        for vc in config.vendors:
            if vc.name.lower() == vendor_lower or any(
                a.lower() == vendor_lower for a in vc.aliases
            ):
                existing_names = {p.name.lower() for p in vc.products}
                added = 0
                for pi in product_items:
                    if pi.name.lower() not in existing_names:
                        vc.products.append(pi)
                        existing_names.add(pi.name.lower())
                        added += 1

                total_added += added
                console.print(create_product_catalog_table(vc.name, vc.products))
                print_success(f"Added {added} products to {vc.name} ({len(product_items) - added} already existed)")
                vendor_found = True
                break

        if not vendor_found:
            console.print(create_product_catalog_table(v_name, product_items))
            print_warning(f"Vendor '{v_name}' not in config. Add vendor first, then re-import.")

    if total_added > 0:
        save_config(config)
        print_success(f"Catalog updated — {total_added} new products total")


@app.command("generate")
def generate(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name."),
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Period for sales velocity."
    ),
) -> None:
    """Generate a recommended purchase order for a vendor."""
    from bizops.parsers.ordering import OrderingEngine
    from bizops.utils.storage import load_toast_reports, save_orders

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task("Generating order...", total=None)
        toast = load_toast_reports(config, start, end)
        engine = OrderingEngine(config)
        order = engine.generate_order(vendor, toast)

    if "error" in order:
        print_error(order["error"])
        raise typer.Exit(1)

    console.print(create_order_table(order))
    console.print()

    velocity = order.get("sales_velocity", {})
    trend = velocity.get("trend_direction", "flat")
    ratio = velocity.get("velocity_ratio", 1.0)
    if trend == "up":
        print_info(f"Sales trending UP ({ratio:.1%} of average) — quantities scaled up")
    elif trend == "down":
        print_info(f"Sales trending DOWN ({ratio:.1%} of average) — quantities scaled down")

    if order.get("budget_warning"):
        print_warning(order["budget_warning"])

    # Save the order
    year_month = datetime.now().strftime("%Y-%m")
    save_orders(config, [order], year_month)
    print_success(f"Order saved — ${order['order_total']:,.2f} for {vendor}")


@app.command("generate-all")
def generate_all(
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Period for sales velocity."
    ),
) -> None:
    """Generate orders for all vendors with products configured."""
    from bizops.parsers.ordering import OrderingEngine
    from bizops.utils.storage import load_toast_reports, save_orders

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task("Generating all orders...", total=None)
        toast = load_toast_reports(config, start, end)
        engine = OrderingEngine(config)
        orders = engine.generate_all_orders(toast)

    if not orders:
        print_warning("No vendors have products with par levels configured.")
        print_info("Use 'bizops orders add-product' to set up product catalogs.")
        raise typer.Exit(0)

    grand_total = 0.0
    for order in orders:
        console.print(create_order_table(order))
        console.print()
        grand_total += order.get("order_total", 0)

    # Save all orders
    year_month = datetime.now().strftime("%Y-%m")
    save_orders(config, orders, year_month)
    print_success(f"Generated {len(orders)} orders — Grand Total: ${grand_total:,.2f}")


@app.command("budget")
def show_budget(
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Period for sales projection."
    ),
) -> None:
    """Show available ordering budget based on sales projections."""
    from bizops.parsers.ordering import OrderingEngine
    from bizops.utils.storage import load_toast_reports

    config = load_config()
    start, end = _resolve_date_range(period)

    toast = load_toast_reports(config, start, end)
    engine = OrderingEngine(config)
    budget_info = engine.get_available_budget(toast)

    console.print(create_budget_panel(budget_info))


@app.command("export")
def export_order(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name."),
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Period for sales velocity."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output file path."
    ),
) -> None:
    """Export a purchase order to Excel."""
    from bizops.commands._export import export_order_sheet
    from bizops.parsers.ordering import OrderingEngine
    from bizops.utils.storage import load_toast_reports

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task("Generating order...", total=None)
        toast = load_toast_reports(config, start, end)
        engine = OrderingEngine(config)
        order = engine.generate_order(vendor, toast)

    if "error" in order:
        print_error(order["error"])
        raise typer.Exit(1)

    with get_spinner() as spinner:
        spinner.add_task("Exporting to Excel...", total=None)
        path = export_order_sheet(order, config, output)

    print_success(f"Purchase order saved to: {path}")


@app.command("template-create")
def template_create(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name."),
    frequency: str = typer.Option("weekly", "--frequency", "-f", help="weekly, biweekly, or monthly."),
    day: int = typer.Option(1, "--day", "-d", help="Day of week (0=Mon..6=Sun)."),
) -> None:
    """Create a recurring order template from a vendor's product catalog."""
    from bizops.utils.config import OrderTemplate

    config = load_config()
    vendor_lower = vendor.lower()
    vendor_config = None

    for vc in config.vendors:
        if vc.name.lower() == vendor_lower or any(
            a.lower() == vendor_lower for a in vc.aliases
        ):
            vendor_config = vc
            break

    if not vendor_config:
        print_error(f"Vendor '{vendor}' not found.")
        raise typer.Exit(1)

    if not vendor_config.products:
        print_error(f"No products configured for {vendor_config.name}.")
        raise typer.Exit(1)

    # Build template from all active products with par levels
    items = []
    for p in vendor_config.products:
        if p.active and p.par_level > 0:
            items.append({
                "product_name": p.name,
                "quantity": p.par_level,
            })

    if not items:
        print_warning("No products with par levels found.")
        raise typer.Exit(0)

    template = OrderTemplate(
        vendor_name=vendor_config.name,
        items=items,
        frequency=frequency,
        day_of_week=day,
    )

    config.order_templates.append(template)
    save_config(config)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_name = days[day] if 0 <= day <= 6 else str(day)
    print_success(f"Template created for {vendor_config.name}: {frequency} on {day_name}")
    print_info(f"  {len(items)} items in template")


@app.command("template-list")
def template_list() -> None:
    """List all recurring order templates."""
    config = load_config()

    if not config.order_templates:
        print_warning("No order templates configured. Use 'bizops orders template-create' to add one.")
        return

    from rich.table import Table

    table = Table(title="Order Templates", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Vendor", style="cyan", width=20)
    table.add_column("Frequency", width=12)
    table.add_column("Day", width=6)
    table.add_column("Items", justify="right", width=6)
    table.add_column("Enabled", width=8)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, t in enumerate(config.order_templates, 1):
        day_name = days[t.day_of_week] if 0 <= t.day_of_week <= 6 else "?"
        enabled = "[green]Yes[/green]" if t.enabled else "[red]No[/red]"
        table.add_row(
            str(i),
            t.vendor_name,
            t.frequency,
            day_name,
            str(len(t.items)),
            enabled,
        )

    console.print(table)


@app.command("template-run")
def template_run(
    vendor: str = typer.Option(..., "--vendor", "-v", help="Vendor name."),
) -> None:
    """Generate an order from a saved template."""
    from bizops.parsers.ordering import OrderingEngine
    from bizops.utils.storage import load_toast_reports, save_orders

    config = load_config()
    vendor_lower = vendor.lower()
    template = None

    for t in config.order_templates:
        if t.vendor_name.lower() == vendor_lower:
            template = t
            break

    if not template:
        print_error(f"No template found for '{vendor}'.")
        raise typer.Exit(1)

    start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    toast = load_toast_reports(config, start, end)

    engine = OrderingEngine(config)
    order = engine.apply_template(template, toast)

    if "error" in order:
        print_error(order["error"])
        raise typer.Exit(1)

    console.print(create_order_table(order))

    year_month = datetime.now().strftime("%Y-%m")
    save_orders(config, [order], year_month)
    print_success(f"Template order generated — ${order['order_total']:,.2f}")
