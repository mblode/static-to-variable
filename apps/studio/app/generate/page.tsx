import { GeneratorWorkspace } from "@/components/generator-workspace";
import { listGenerationJobs } from "@/lib/generation.server";

export const metadata = { title: "Generate — Static to Variable" };
export const dynamic = "force-dynamic";

export default async function GeneratePage() {
  const jobs = await listGenerationJobs();

  return (
    <main>
      <GeneratorWorkspace initialJobs={jobs} />
    </main>
  );
}
