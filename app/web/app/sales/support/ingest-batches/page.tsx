import { redirect } from "next/navigation";

export default function LegacyIngestBatchesRedirect() {
  redirect("/sales/management/data");
}
