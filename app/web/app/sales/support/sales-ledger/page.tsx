import { redirect } from "next/navigation";

export default function LegacySalesLedgerRedirect() {
  redirect("/sales/management/ledger");
}
