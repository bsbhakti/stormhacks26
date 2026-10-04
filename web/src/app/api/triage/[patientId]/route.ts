import { getPatientDetail } from "@/lib/triage";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ patientId: string }> },
) {
  const { patientId } = await context.params;
  try {
    const detail = await getPatientDetail(decodeURIComponent(patientId));
    if (!detail) {
      return Response.json({ error: "Patient is not in the active queue" }, { status: 404 });
    }
    return Response.json(detail, {
      headers: {
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    console.error("Unable to load patient detail", error);
    return Response.json(
      { error: "Unable to load patient detail from TimescaleDB" },
      { status: 503 },
    );
  }
}
