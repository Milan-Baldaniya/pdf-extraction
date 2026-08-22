import { api } from "@/lib/api";

/**
 * Tenant-wise display names for the Semantic Intelligence tabs.
 *
 * The keys below are contract: they match the TabsTrigger/TabsContent values in
 * the viewer and the tab_key column server-side. Only the label is renameable.
 */
export const DEFAULT_TAB_LABELS: Record<string, string> = {
  knowledge: "Knowledge",
  ability: "Ability",
  skill: "Skill",
  competency: "Competency",
  blooms: "Bloom's",
  dok: "DOK",
  prerequisite: "Prerequisites",
  misconception: "Misconceptions",
  realworld: "Real World",
  pedagogy: "Pedagogy",
  objectives: "Objectives",
  outcomes: "Outcomes",
  blueprint: "Blueprint",
  rubrics: "Rubrics",
  relationships: "Relationships",
  evidence: "Evidence",
  reasoning: "AI Reasoning",
  activities: "Activities",
};

/** Tab strip for the current 13-dimension concept layout, in display order. */
export const CONCEPT_TAB_KEYS = [
  "knowledge",
  "ability",
  "skill",
  "competency",
  "blooms",
  "dok",
  "prerequisite",
  "misconception",
  "realworld",
  "pedagogy",
  "objectives",
  "outcomes",
  "blueprint",
  "rubrics",
  "relationships",
  "evidence",
  "reasoning",
] as const;

/** Tab strip for chapters still stored under the older 6-dimension schema. */
export const LEGACY_TAB_KEYS = [
  "knowledge",
  "pedagogy",
  "misconception",
  "realworld",
  "activities",
  "outcomes",
] as const;

/** The tenant used when the extraction row carries no sub_institute_id. */
export const DEFAULT_SUB_INSTITUTE_ID = 341;

export interface TabLabel {
  tab_key: string;
  default_label: string;
  label: string;
  is_custom: boolean;
}

export interface TabLabelResponse {
  sub_institute_id: number;
  tabs: TabLabel[];
}

/** tab_key -> resolved label, ready to index straight from the tab strip. */
export function toLabelMap(tabs: TabLabel[]): Record<string, string> {
  return tabs.reduce<Record<string, string>>((acc, t) => {
    acc[t.tab_key] = t.label;
    return acc;
  }, {});
}

export async function fetchTabLabels(
  subInstituteId: number = DEFAULT_SUB_INSTITUTE_ID
): Promise<TabLabelResponse> {
  const { data } = await api.get<TabLabelResponse>("/semantic-intelligence-tabs", {
    params: { sub_institute_id: subInstituteId },
  });
  return data;
}

/**
 * Persist renames for one tenant. A blank value clears that tab's override and
 * restores the default name.
 */
export async function saveTabLabels(
  subInstituteId: number,
  labels: Record<string, string>
): Promise<TabLabelResponse> {
  const { data } = await api.put<TabLabelResponse>("/semantic-intelligence-tabs", {
    sub_institute_id: subInstituteId,
    labels,
  });
  return data;
}

export async function resetTabLabels(
  subInstituteId: number
): Promise<TabLabelResponse> {
  const { data } = await api.delete<TabLabelResponse>("/semantic-intelligence-tabs", {
    params: { sub_institute_id: subInstituteId },
  });
  return data;
}
