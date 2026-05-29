import { getJSON } from "../../lib/api";
import DashboardViewer from "./viewer";

type Batch = { id: number; business_date: string; file_name: string; row_count: number; status: string; uploaded_at: string };

async function fetchBatches(): Promise<Batch[]> {
 try { return await getJSON<Batch[]>("/api/batches"); } catch { return []; }
}

export default async function Page() {
 const batches = await fetchBatches();
 return <DashboardViewer batches={batches} />;
}
