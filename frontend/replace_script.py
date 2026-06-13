import re

path = r'c:\Users\MILAN\Downloads\pdf extraction\frontend\src\components\semantic-intelligence-viewer.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add Lucide imports
content = content.replace(
    'import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";',
    'import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";\nimport { Brain, Target, Zap, Award, Layers, BarChart, Link as LinkIcon, AlertTriangle, Globe, Lightbulb, Flag, CheckCircle, FileText } from "lucide-react";'
)

# 2. Replace TabsTrigger
tabs_replacement = '''<TabsTrigger value="knowledge" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Brain className="w-3.5 h-3.5"/> Knowledge</TabsTrigger>
                        <TabsTrigger value="ability" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Target className="w-3.5 h-3.5"/> Ability</TabsTrigger>
                        <TabsTrigger value="skill" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Zap className="w-3.5 h-3.5"/> Skill</TabsTrigger>
                        <TabsTrigger value="competency" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Award className="w-3.5 h-3.5"/> Competency</TabsTrigger>
                        <TabsTrigger value="blooms" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Layers className="w-3.5 h-3.5"/> Bloom's</TabsTrigger>
                        <TabsTrigger value="dok" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><BarChart className="w-3.5 h-3.5"/> DOK</TabsTrigger>
                        <TabsTrigger value="prerequisite" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><LinkIcon className="w-3.5 h-3.5"/> Prerequisites</TabsTrigger>
                        <TabsTrigger value="misconception" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5"/> Misconceptions</TabsTrigger>
                        <TabsTrigger value="realworld" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Globe className="w-3.5 h-3.5"/> Real World</TabsTrigger>
                        <TabsTrigger value="pedagogy" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Lightbulb className="w-3.5 h-3.5"/> Pedagogy</TabsTrigger>
                        <TabsTrigger value="objectives" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><Flag className="w-3.5 h-3.5"/> Objectives</TabsTrigger>
                        <TabsTrigger value="outcomes" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5"/> Outcomes</TabsTrigger>
                        <TabsTrigger value="blueprint" className="rounded-lg px-3 py-1.5 text-xs cursor-pointer flex items-center gap-1.5"><FileText className="w-3.5 h-3.5"/> Blueprint</TabsTrigger>'''

content = re.sub(
    r'<TabsTrigger value="knowledge".*?Blueprint</TabsTrigger>',
    tabs_replacement,
    content,
    flags=re.DOTALL
)

# 3. Replace TabsContent space-y-4 with Grids
def wrap_with_grid(tab_val, arr_name):
    # Matches <TabsContent value="..."> \n {conceptObj...} \n </TabsContent>
    # Note: we should just replace 'space-y-4' with 'mt-4' and wrap the inner map in a div.
    pattern = r'(<TabsContent value="' + tab_val + r'" className="space-y-4">\s*)({conceptObj\.' + arr_name + r'\?\.map[^\}]+\}\)\s*\))(\s*</TabsContent>)'
    
    def replacer(m):
        return m.group(1).replace('space-y-4', 'mt-4') + '<div className="grid grid-cols-1 lg:grid-cols-2 gap-4">\n' + m.group(2) + '\n</div>' + m.group(3)
        
    return re.sub(pattern, replacer, content, flags=re.DOTALL)

content = wrap_with_grid('knowledge', 'knowledge_items')
content = wrap_with_grid('ability', 'abilities')
content = wrap_with_grid('competency', 'competencies')
content = wrap_with_grid('prerequisite', 'prerequisites')
content = wrap_with_grid('misconception', 'misconceptions')
content = wrap_with_grid('pedagogy', 'pedagogy_recommendations')
content = wrap_with_grid('objectives', 'learning_objectives')
content = wrap_with_grid('outcomes', 'learning_outcomes')
content = wrap_with_grid('blueprint', 'assessment_blueprint')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully replaced layout!")
