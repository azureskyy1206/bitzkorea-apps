import { getJSON } from "../../../lib/api";
import SalesChangesClient from "./sales-changes-client";

type Batch = {
  id: number;
  file_name: string;
  business_date: string;
  row_count: number;
  status: string;
  uploaded_at: string;
};

async function fetchBatches(): Promise<Batch[]> {
  try {
    return await getJSON<Batch[]>("/api/batches");
  } catch {
    return [];
  }
}

export default async function SalesChangesPage() {
  const batches = await fetchBatches();
  return <SalesChangesClient batches={batches} />;
}
