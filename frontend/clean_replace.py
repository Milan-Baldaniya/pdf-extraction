import re

path = r'c:\Users\MILAN\Downloads\pdf extraction\frontend\src\components\semantic-intelligence-viewer.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Imports
content = content.replace(
    'import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";',
    'import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";\nimport { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";\nimport { Brain, Target, Zap, Award, Layers, BarChart, Link as LinkIcon, AlertTriangle, Globe, Lightbulb, Flag, CheckCircle, FileText } from "lucide-react";'
)

# 2. Add InfoTooltip
content = content.replace(
    'export function SemanticIntelligenceViewer',
    '''function InfoTooltip({ children, content, className }: any) {
  return (
    <Tooltip>
      <TooltipTrigger className={`cursor-pointer inline-flex items-center ${className || ""}`}>
        {children}
      </TooltipTrigger>
      <TooltipContent 
        sideOffset={8}
        className="max-w-[320px] p-4 text-sm leading-relaxed bg-white/95 dark:bg-black/95 backdrop-blur-xl border border-black/10 dark:border-white/10 shadow-2xl rounded-2xl text-foreground font-medium z-[100]"
      >
        {content}
      </TooltipContent>
    </Tooltip>
  );
}

export function SemanticIntelligenceViewer'''
)

# 3. Add TooltipProvider
content = content.replace(
    '<div className="w-full flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-4 duration-700">',
    '<TooltipProvider delayDuration={100}>\n      <div className="w-full flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-4 duration-700">'
)
content = content.replace(
    '      </div>\n    </div>\n  );\n}',
    '      </div>\n      </div>\n    </TooltipProvider>\n  );\n}'
)

# 4. Replace Icons in TabsTrigger
tabs_replacements = [
    ('<TabsTrigger value="knowledge" className="rounded-lg px-3 py-1.5 text-xs">Knowledge</TabsTrigger>', '<TabsTrigger value="knowledge" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Brain className="w-3.5 h-3.5"/> Knowledge</TabsTrigger>'),
    ('<TabsTrigger value="ability" className="rounded-lg px-3 py-1.5 text-xs">Ability</TabsTrigger>', '<TabsTrigger value="ability" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Target className="w-3.5 h-3.5"/> Ability</TabsTrigger>'),
    ('<TabsTrigger value="skill" className="rounded-lg px-3 py-1.5 text-xs">Skill</TabsTrigger>', '<TabsTrigger value="skill" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Zap className="w-3.5 h-3.5"/> Skill</TabsTrigger>'),
    ('<TabsTrigger value="competency" className="rounded-lg px-3 py-1.5 text-xs">Competency</TabsTrigger>', '<TabsTrigger value="competency" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Award className="w-3.5 h-3.5"/> Competency</TabsTrigger>'),
    ('<TabsTrigger value="blooms" className="rounded-lg px-3 py-1.5 text-xs">Bloom\'s</TabsTrigger>', '<TabsTrigger value="blooms" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Layers className="w-3.5 h-3.5"/> Bloom\'s</TabsTrigger>'),
    ('<TabsTrigger value="dok" className="rounded-lg px-3 py-1.5 text-xs">DOK</TabsTrigger>', '<TabsTrigger value="dok" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><BarChart className="w-3.5 h-3.5"/> DOK</TabsTrigger>'),
    ('<TabsTrigger value="prerequisite" className="rounded-lg px-3 py-1.5 text-xs">Prerequisites</TabsTrigger>', '<TabsTrigger value="prerequisite" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><LinkIcon className="w-3.5 h-3.5"/> Prerequisites</TabsTrigger>'),
    ('<TabsTrigger value="misconception" className="rounded-lg px-3 py-1.5 text-xs">Misconceptions</TabsTrigger>', '<TabsTrigger value="misconception" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5"/> Misconceptions</TabsTrigger>'),
    ('<TabsTrigger value="realworld" className="rounded-lg px-3 py-1.5 text-xs">Real World</TabsTrigger>', '<TabsTrigger value="realworld" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Globe className="w-3.5 h-3.5"/> Real World</TabsTrigger>'),
    ('<TabsTrigger value="pedagogy" className="rounded-lg px-3 py-1.5 text-xs">Pedagogy</TabsTrigger>', '<TabsTrigger value="pedagogy" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Lightbulb className="w-3.5 h-3.5"/> Pedagogy</TabsTrigger>'),
    ('<TabsTrigger value="objectives" className="rounded-lg px-3 py-1.5 text-xs">Objectives</TabsTrigger>', '<TabsTrigger value="objectives" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Flag className="w-3.5 h-3.5"/> Objectives</TabsTrigger>'),
    ('<TabsTrigger value="outcomes" className="rounded-lg px-3 py-1.5 text-xs">Outcomes</TabsTrigger>', '<TabsTrigger value="outcomes" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5"/> Outcomes</TabsTrigger>'),
    ('<TabsTrigger value="blueprint" className="rounded-lg px-3 py-1.5 text-xs">Blueprint</TabsTrigger>', '<TabsTrigger value="blueprint" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><FileText className="w-3.5 h-3.5"/> Blueprint</TabsTrigger>'),
]

for old_s, new_s in tabs_replacements:
    content = content.replace(old_s, new_s)

# 5. Add Tooltips to tags
tags_replacements = [
    (
        '<div className="flex gap-2 text-xs">\n                              <span className="bg-black/5 px-2 py-1 rounded">Imp: {k.importance}</span>\n                              <span className="bg-black/5 px-2 py-1 rounded">Diff: {k.difficulty}</span>\n                              <span className="bg-black/5 px-2 py-1 rounded">Ret: {k.retention_priority}</span>\n                            </div>',
        '<div className="flex gap-2 text-xs mt-3">\n                              <InfoTooltip content="Importance: Indicates if this knowledge is core to passing exams or just supporting context."><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Importance: {k.importance}</span></InfoTooltip>\n                              <InfoTooltip content="Difficulty: Defines how hard this concept is for students to grasp initially."><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Difficulty: {k.difficulty}</span></InfoTooltip>\n                              <InfoTooltip content="Retention: Measures how critical it is for the student to remember this long-term."><span className="bg-black/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Retention: {k.retention_priority}</span></InfoTooltip>\n                            </div>'
    ),
    (
        '<div className="flex items-center gap-2 mb-2">\n                              <Badge className="bg-blue-500 text-white">{a.ability_type}</Badge>\n                              <span className="text-sm font-medium">Complexity: {a.complexity}</span>\n                            </div>',
        '<div className="flex items-center gap-2 mb-3">\n                              <InfoTooltip content="Ability Type: The specific cognitive action the student must perform."><Badge className="bg-blue-500 text-white hover:bg-blue-600">{a.ability_type}</Badge></InfoTooltip>\n                              <InfoTooltip content="Complexity: Defines the cognitive load required to perform this ability, helping teachers pace lessons."><span className="text-sm font-medium bg-blue-500/10 px-2 py-0.5 rounded text-blue-800 dark:text-blue-200">Complexity: {a.complexity}</span></InfoTooltip>\n                              {a.measurable && <InfoTooltip content="Measurable: Indicates if a teacher can easily test this ability."><span className="text-xs bg-emerald-500/10 text-emerald-700 px-2 py-0.5 rounded">Measurable</span></InfoTooltip>}\n                            </div>'
    ),
    (
        '<Badge variant="outline" className="mb-2 border-teal-500/30 text-teal-700">{s.skill_type}</Badge>\n                              <div className="flex gap-2 text-xs text-muted-foreground">\n                                <span>Dev: {s.development_level}</span> • <span>Trans: {s.transferability}</span>\n                              </div>',
        '<InfoTooltip content="Skill Type: Categorizes the skill (e.g., Analytical, Practical)."><Badge variant="outline" className="mb-2 border-teal-500/30 text-teal-700">{s.skill_type}</Badge></InfoTooltip>\n                              <div className="flex gap-2 text-xs text-muted-foreground mt-2">\n                                <InfoTooltip content="Development Level: Indicates whether this is an introductory, intermediate, or advanced skill."><span className="bg-black/5 dark:bg-white/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Development: {s.development_level}</span></InfoTooltip>\n                                <InfoTooltip content="Transferability: Measures how easily this skill can be applied to other subjects or real-world scenarios."><span className="bg-black/5 dark:bg-white/5 px-2 py-1 rounded hover:bg-black/10 transition-colors">Transferability: {s.transferability}</span></InfoTooltip>\n                              </div>'
    ),
    (
        '<Badge variant="secondary">{p.necessity}</Badge>',
        '<InfoTooltip content="Necessity: Whether this prerequisite is absolutely required or just helpful."><Badge variant="secondary">{p.necessity}</Badge></InfoTooltip>'
    ),
    (
        '<div className="flex gap-2">\n                              <Badge variant="outline" className="border-red-500/30 text-red-700">Freq: {m.frequency}</Badge>\n                              <Badge variant="outline" className="border-red-500/30 text-red-700">Sev: {m.severity}</Badge>\n                            </div>',
        '<div className="flex gap-2 mt-3">\n                              <InfoTooltip content="Frequency: How often students typically make this mistake."><Badge variant="outline" className="border-red-500/30 text-red-700 hover:bg-red-500/10">Frequency: {m.frequency}</Badge></InfoTooltip>\n                              <InfoTooltip content="Severity: How badly this misconception damages future learning if not corrected."><Badge variant="outline" className="border-red-500/30 text-red-700 hover:bg-red-500/10">Severity: {m.severity}</Badge></InfoTooltip>\n                            </div>'
    ),
    (
        '<Badge variant="outline">{p.effectiveness} Effectiveness</Badge>',
        '<InfoTooltip content="Effectiveness: Rating of how well this teaching method works for this concept."><Badge variant="outline" className="hover:bg-black/5">{p.effectiveness} Effectiveness</Badge></InfoTooltip>'
    ),
    (
        '<div className="flex gap-2 mt-2">\n                                  <Badge variant="secondary" className="text-[10px]">{lo.objective_type}</Badge>\n                                  <Badge variant="outline" className="text-[10px]">{lo.priority} Priority</Badge>\n                                </div>',
        '<div className="flex gap-2 mt-3">\n                                  <InfoTooltip content="Objective Type: Categorizes the goal (e.g., Cognitive, Psychomotor)."><Badge variant="secondary" className="text-[10px] hover:bg-secondary/80">{lo.objective_type}</Badge></InfoTooltip>\n                                  <InfoTooltip content="Priority: Indicates if this objective is essential or optional."><Badge variant="outline" className="text-[10px] hover:bg-black/5">{lo.priority} Priority</Badge></InfoTooltip>\n                                </div>'
    ),
    (
        '<div className="flex gap-2 mt-2">\n                                  <Badge variant="secondary" className="text-[10px]">{lo.outcome_type}</Badge>\n                                  {lo.measurable && <Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-600">Measurable</Badge>}\n                                </div>',
        '<div className="flex gap-2 mt-3">\n                                  <InfoTooltip content="Outcome Type: The nature of the learning result."><Badge variant="secondary" className="text-[10px] hover:bg-secondary/80">{lo.outcome_type}</Badge></InfoTooltip>\n                                  {lo.measurable && <InfoTooltip content="Measurable: Indicates if this outcome can be explicitly tested."><Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-600 hover:bg-emerald-500/10">Measurable</Badge></InfoTooltip>}\n                                </div>'
    ),
    (
        '<div className="flex flex-wrap gap-2">\n                              <Badge variant="outline" className="bg-white/50 dark:bg-black/50">{ab.assessment_type}</Badge>\n                              <Badge variant="outline" className="bg-white/50 dark:bg-black/50">{ab.difficulty}</Badge>\n                              <Badge variant="outline" className="bg-white/50 dark:bg-black/50">Bloom: {ab.bloom_level}</Badge>\n                              <Badge variant="outline" className="bg-white/50 dark:bg-black/50">DOK {ab.dok_level}</Badge>\n                            </div>',
        '<div className="flex flex-wrap gap-2 mt-3">\n                              <InfoTooltip content="Assessment Type: The format of the question (e.g., MCQ, Short Answer)."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">{ab.assessment_type}</Badge></InfoTooltip>\n                              <InfoTooltip content="Difficulty: The expected challenge level for the student."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">Difficulty: {ab.difficulty}</Badge></InfoTooltip>\n                              <InfoTooltip content="Bloom\'s Level: The cognitive skill targeted by this question."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">Bloom: {ab.bloom_level}</Badge></InfoTooltip>\n                              <InfoTooltip content="Depth of Knowledge (DOK): The complexity of reasoning required."><Badge variant="outline" className="bg-white/50 dark:bg-black/50 hover:bg-black/5">DOK {ab.dok_level}</Badge></InfoTooltip>\n                            </div>'
    )
]

for old_s, new_s in tags_replacements:
    content = content.replace(old_s, new_s)

# 6. Apply Grids
tabs_to_gridify = ["knowledge", "ability", "misconception", "pedagogy", "objectives", "outcomes", "blueprint"]
for tab in tabs_to_gridify:
    content = content.replace(
        f'<TabsContent value="{tab}" className="space-y-4">',
        f'<TabsContent value="{tab}" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">'
    )

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Complete")
