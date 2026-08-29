import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { projectsApi } from "@/lib/api/resources";

/** Resolves `:projectId` from the route and fetches the project. */
export function useProject() {
  const { projectId } = useParams<{ projectId: string }>();
  const query = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: Boolean(projectId),
  });
  return { projectId: projectId!, ...query };
}
