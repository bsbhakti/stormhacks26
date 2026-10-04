import { getTriageQueue } from "@/lib/triage";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const queue = await getTriageQueue();
    return Response.json(queue, {
      headers: {
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    console.error("Unable to load triage queue", error);
    return Response.json(
      { error: "Unable to load triage data from TimescaleDB" },
      { status: 503 },
    );
  }
}
