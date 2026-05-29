import { redirect } from "next/navigation";

export default function LegacySalesDashboardRedirect() {
  redirect("/sales/management/dashboard");
}
