"use client";

import { useState, useEffect, useMemo } from "react";
import { ChevronLeft, ChevronRight, Calendar as CalendarIcon, Clock, AlertCircle, Search, LayoutGrid, CheckSquare, BrainCircuit, Plus, BookOpen, ArrowLeft } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import Link from "next/link";

export default function MasterCalendarPage() {
  const [loading, setLoading] = useState(false);
  
  // View State
  const [viewMode, setViewMode] = useState<"day" | "week" | "month">("week");
  const [currentDate, setCurrentDate] = useState<Date>(new Date(2025, 5, 19)); // Default to June 19, 2025 based on screenshots

  // Dropdowns
  const [institutes, setInstitutes] = useState<any[]>([]);
  const [standards, setStandards] = useState<any[]>([]);
  const [divisions, setDivisions] = useState<any[]>([]);
  const [years, setYears] = useState<number[]>([]);
  
  const [instId, setInstId] = useState("");
  const [stdId, setStdId] = useState("");
  const [divId, setDivId] = useState("");
  const [year, setYear] = useState("");

  // Data
  const [periods, setPeriods] = useState<any[]>([]);
  
  // Sidebar state
  const [selectedSubjects, setSelectedSubjects] = useState<Set<number>>(new Set());
  
  // Hover effect state
  const [hoveredSubjectId, setHoveredSubjectId] = useState<number | null>(null);
  const [expandedDay, setExpandedDay] = useState<string | null>(null);

  // Fetch initial dropdowns
  useEffect(() => {
    fetch("http://localhost:8000/lesson-intelligence/dropdowns")
      .then(res => res.json())
      .then(data => {
        if (data.status === "success") {
          setInstitutes(data.institutes || []);
        }
      });
  }, []);

  // Fetch filtered dropdowns when Institute changes
  useEffect(() => {
    if (!instId) return;
    fetch(`http://localhost:8000/lesson-intelligence/dropdowns/filter?sub_institute_id=${instId}`)
      .then(res => res.json())
      .then(data => {
        setStandards(data.standards || []);
        setDivisions(data.divisions || []);
        setYears(data.years || []);
      });
  }, [instId]);

  // Fetch master calendar data
  const fetchCalendar = async () => {
    if (!instId || !stdId || !divId || !year) return;
    setLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/master-calendar/${instId}/${stdId}/${divId}?syear=${year}`);
      const data = await res.json();
      if (data.status === "success") {
        setPeriods(data.periods || []);
        
        // Auto-select all unique subjects
        const subs = new Set<number>();
        (data.periods || []).forEach((p: any) => subs.add(p.subject_id));
        setSelectedSubjects(subs);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Derived unique subjects for sidebar
  const uniqueSubjects = useMemo(() => {
    const map = new Map();
    periods.forEach(p => {
      if (!map.has(p.subject_id)) {
        map.set(p.subject_id, p.subject_name);
      }
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [periods]);

  // Advanced DSA optimization: Parse actual times to build an absolute timeline (Google Calendar style)
  const timeToMinutes = (timeStr: string | null) => {
    if (!timeStr || timeStr === "-" || timeStr === "TBD") return null;
    const parts = timeStr.split(":");
    if (parts.length >= 2) {
      let h = parseInt(parts[0], 10);
      let m = parseInt(parts[1], 10);
      if (isNaN(h) || isNaN(m)) return null;
      return h * 60 + m;
    }
    return null;
  };

  const timelineData = useMemo(() => {
    let min = 24 * 60;
    let max = 0;
    let hasValidTimes = false;

    // First pass: find min/max of valid times
    periods.forEach(p => {
      const st = timeToMinutes(p.start_time);
      const et = timeToMinutes(p.end_time);
      
      const isValidDuration = st !== null && !isNaN(st) && et !== null && !isNaN(et) && (et - st >= 15);
      
      if (isValidDuration) {
        if (st < min) min = st;
        if (et > max) max = et;
        hasValidTimes = true;
      }
    });

    // Always build slotToFakeTime to handle ANY missing times
    const slotToFakeTime = new Map<string, {start: number, end: number}>();
    const slots = Array.from(new Set(periods.map(p => p.slot))).sort((a, b) => {
      const aNum = parseInt(a?.replace(/\D/g, '') || '0') || 0;
      const bNum = parseInt(b?.replace(/\D/g, '') || '0') || 0;
      return aNum - bNum;
    });

    let currentFakeStart = 7 * 60; // Start from 7 AM
    slots.forEach((s) => {
      const start = currentFakeStart;
      const end = start + 60; // 1 hour fallback slots
      slotToFakeTime.set(s, { start, end });
      currentFakeStart += 60;
    });

    // Second pass: Update min/max to include fake times for any periods that lack real times
    periods.forEach(p => {
      const st = timeToMinutes(p.start_time);
      const et = timeToMinutes(p.end_time);
      const isValidDuration = st !== null && !isNaN(st) && et !== null && !isNaN(et) && (et - st >= 15);
      
      if (!isValidDuration) {
         const fake = slotToFakeTime.get(p.slot);
         if (fake) {
            if (fake.start < min) min = fake.start;
            if (fake.end > max) max = fake.end;
         }
      }
    });

    if (min === 24 * 60) min = 7 * 60;
    if (max === 0) max = 15 * 60;

    // Pad by 1 hour top and bottom for visual breathing room
    min = Math.max(0, Math.floor(min / 60) * 60 - 60);
    // If the user requested to always start from 7am, let's force the absolute min timeline edge to 7am if it isn't earlier
    if (min > 7 * 60) {
      min = 7 * 60;
    }
    
    max = Math.min(24 * 60, Math.ceil(max / 60) * 60 + 60);

    return { minTime: min, maxTime: max, hasValidTimes, slotToFakeTime };
  }, [periods]);

  const totalMins = Math.max(60, timelineData.maxTime - timelineData.minTime);
  const totalHours = Math.ceil(totalMins / 60);

  // Date helpers
  const startOfWeek = new Date(currentDate);
  startOfWeek.setDate(currentDate.getDate() - currentDate.getDay()); // Sunday
  
  const weekDays = Array.from({ length: 7 }).map((_, i) => {
    const d = new Date(startOfWeek);
    d.setDate(startOfWeek.getDate() + i);
    return d;
  });

  const monthDays = useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    
    const days = [];
    
    // Previous month padding
    const startPadding = firstDay.getDay(); // 0 (Sun) to 6 (Sat)
    for (let i = startPadding - 1; i >= 0; i--) {
      days.push(new Date(year, month, -i));
    }
    
    // Current month days
    for (let i = 1; i <= lastDay.getDate(); i++) {
      days.push(new Date(year, month, i));
    }
    
    // Next month padding
    const remaining = 42 - days.length; // 6 rows * 7 columns = 42
    for (let i = 1; i <= remaining; i++) {
      days.push(new Date(year, month + 1, i));
    }
    
    return days;
  }, [currentDate]);

  const nextPeriod = () => {
    const d = new Date(currentDate);
    if (viewMode === "day") d.setDate(d.getDate() + 1);
    if (viewMode === "week") d.setDate(d.getDate() + 7);
    if (viewMode === "month") d.setMonth(d.getMonth() + 1);
    setCurrentDate(d);
  };

  const prevPeriod = () => {
    const d = new Date(currentDate);
    if (viewMode === "day") d.setDate(d.getDate() - 1);
    if (viewMode === "week") d.setDate(d.getDate() - 7);
    if (viewMode === "month") d.setMonth(d.getMonth() - 1);
    setCurrentDate(d);
  };

  const isToday = (d: Date) => {
    const today = new Date();
    return d.getDate() === today.getDate() && d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear();
  };

  // Format YYYY-MM-DD
  const formatDateStr = (d: Date) => {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };

  // Generate subject colors consistently
  const getSubjectColor = (subId: number) => {
    const colors = [
      "from-blue-500 to-indigo-500",
      "from-emerald-400 to-teal-500",
      "from-orange-400 to-red-500",
      "from-purple-500 to-pink-500",
      "from-amber-400 to-orange-500"
    ];
    return colors[subId % colors.length];
  };

  return (
    <div className="flex h-[100dvh] max-h-[100dvh] bg-slate-50 dark:bg-[#0a0a0a] text-slate-900 dark:text-slate-100 overflow-hidden font-sans relative">
      
      {/* Liquid Glass Background Effects */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-pink-500/20 dark:bg-pink-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />

      {/* Global Header */}
      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all hover:bg-white/50 dark:hover:bg-black/50 overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-full before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-500/10 shadow-inner border-[0.5px] border-blue-500/20">
              <CalendarIcon className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90">
              MASTER CALENDAR
            </span>
          </div>

          <div className="flex items-center gap-3">
            <a
              href="/"
              className="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium text-foreground/70 bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:hover:bg-white/10 hover:text-foreground transition-all border-[0.5px] border-transparent hover:border-black/10 dark:hover:border-white/10"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to Home
            </a>
          </div>
        </div>
      </header>

      {/* INNER WRAPPER TO PUSH CONTENT BELOW HEADER WITHOUT BREAKING BACKGROUND */}
      <div className="flex h-full w-full pt-24 relative z-10">
        
        {/* SIDEBAR */}
        <div className="w-72 shrink-0 border-r border-slate-200/50 dark:border-slate-800/50 bg-white/40 dark:bg-black/40 backdrop-blur-3xl flex flex-col shadow-[4px_0_24px_rgba(0,0,0,0.02)]">


        <div className="p-6 overflow-y-auto custom-scrollbar flex flex-col gap-6">
          {/* Configuration */}
          <div className="w-full bg-white/50 dark:bg-black/50 backdrop-blur-3xl border border-black/10 dark:border-white/10 rounded-3xl p-6 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">Configuration</h2>
            <CustomSelect 
              options={institutes.map(i => ({label: i.name, value: String(i.id)}))} 
              value={instId} 
              onChange={setInstId} 
              placeholder="Select Institute..." 
            />
            <CustomSelect 
              options={standards.map(s => ({label: s.name, value: String(s.id)}))} 
              value={stdId} 
              onChange={setStdId} 
              placeholder="Select Standard..." 
            />
            <CustomSelect 
              options={divisions.map(d => ({label: d.name, value: String(d.id)}))} 
              value={divId} 
              onChange={setDivId} 
              placeholder="Select Division..." 
            />
            <CustomSelect 
              options={years.map(y => ({label: String(y), value: String(y)}))} 
              value={year} 
              onChange={setYear} 
              placeholder="Select Year..." 
            />
            <button 
              onClick={fetchCalendar}
              disabled={loading || !instId || !stdId || !divId || !year}
              className="w-full mt-4 py-3.5 rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] text-foreground font-semibold transition-all hover:bg-blue-500/10 hover:text-blue-600 dark:hover:text-blue-400 border-transparent hover:border-blue-500/20 disabled:opacity-50 flex justify-center items-center gap-2"
            >
              {loading ? "Loading..." : "Load Timetable"}
            </button>
          </div>

          {/* Subjects Filter */}
          {uniqueSubjects.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 pl-2">Subjects Displayed</h2>
              <div className="space-y-1">
                {uniqueSubjects.map(sub => (
                  <label key={sub.id} className="flex items-center gap-3 p-2 rounded-xl hover:bg-slate-100/50 dark:hover:bg-white/5 cursor-pointer transition-colors">
                    <input 
                      type="checkbox" 
                      className="w-4 h-4 rounded text-blue-600 border-slate-300 dark:border-slate-600 focus:ring-blue-500 dark:bg-slate-800"
                      checked={selectedSubjects.has(sub.id)}
                      onChange={(e) => {
                        const next = new Set(selectedSubjects);
                        e.target.checked ? next.add(sub.id) : next.delete(sub.id);
                        setSelectedSubjects(next);
                      }}
                    />
                    <div className={`w-3 h-3 rounded-full bg-gradient-to-br ${getSubjectColor(sub.id)} shadow-sm`} />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">{sub.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* MAIN CONTENT */}
      <div className="flex-1 flex flex-col min-w-0 z-10 relative">
        {/* TOP BAR */}
        <div className="h-20 shrink-0 border-b border-slate-200/50 dark:border-slate-800/50 bg-white/40 dark:bg-black/40 backdrop-blur-3xl flex items-center justify-between px-8">
          <div className="flex items-center gap-6">
            <button 
              onClick={() => setCurrentDate(new Date())}
              className="px-5 py-2 text-sm font-semibold rounded-full border border-slate-200 dark:border-slate-700 bg-white/50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors shadow-sm backdrop-blur-md"
            >
              Today
            </button>
            <div className="flex items-center gap-2">
              <button onClick={prevPeriod} className="p-2 rounded-full border-[0.5px] border-black/5 dark:border-white/10 hover:bg-slate-200/50 dark:hover:bg-white/10 transition-colors bg-white/50 dark:bg-slate-800/50 shadow-sm backdrop-blur-md">
                <ChevronLeft className="w-5 h-5" />
              </button>
              <button onClick={nextPeriod} className="p-2 rounded-full border-[0.5px] border-black/5 dark:border-white/10 hover:bg-slate-200/50 dark:hover:bg-white/10 transition-colors bg-white/50 dark:bg-slate-800/50 shadow-sm backdrop-blur-md">
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>
            <h2 className="text-2xl font-normal text-slate-800 dark:text-slate-100">
              {currentDate.toLocaleString('default', { month: 'long', year: 'numeric' })}
            </h2>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex p-1 rounded-full bg-slate-200/50 dark:bg-slate-800/50 backdrop-blur-xl border border-slate-300/30 dark:border-slate-700/30 shadow-inner">
              {(["day", "week", "month"] as const).map(m => (
                <button
                  key={m}
                  onClick={() => setViewMode(m)}
                  className={`px-6 py-2 rounded-full text-sm font-medium capitalize transition-all ${viewMode === m ? 'bg-white dark:bg-slate-700 shadow-md text-blue-600 dark:text-white' : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'}`}
                >
                  {m}
                </button>
              ))}
            </div>
            
            <Link href="/lesson-plan">
              <button className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-blue-600 hover:bg-blue-700 text-white font-medium shadow-md shadow-blue-500/20 transition-all ml-2 text-sm">
                <Plus className="w-4 h-4" />
                Create Lesson Plan
              </button>
            </Link>
          </div>
        </div>

        {/* CALENDAR GRID */}
        <div className="flex-1 bg-slate-50/50 dark:bg-transparent relative p-6 flex flex-col min-h-0">
          
          {/* WEEK & DAY TIMELINE VIEW */}
          {(viewMode === "week" || viewMode === "day") && (() => {
            const renderDays = viewMode === "day" ? [currentDate] : weekDays;
            
            return (
            <div className="w-full flex-1 flex flex-col bg-white/40 dark:bg-black/20 backdrop-blur-2xl rounded-[2rem] border border-white/40 dark:border-white/5 shadow-xl overflow-hidden min-h-0">
              
              {/* Header */}
              <div className={`grid border-b border-slate-200/50 dark:border-slate-800/50 shrink-0 ${viewMode === "day" ? "grid-cols-[80px_minmax(0,1fr)]" : "grid-cols-[80px_repeat(7,minmax(0,1fr))]"}`}>
                <div className="border-r border-slate-200/50 dark:border-slate-800/50"></div>
                {renderDays.map((d, i) => (
                  <div key={i} className="py-2 flex flex-col items-center justify-center gap-0.5 border-r border-slate-200/50 dark:border-slate-800/50 last:border-0 relative">
                    <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">{d.toLocaleDateString('en-US', { weekday: 'short' })}</span>
                    <div className={`w-8 h-8 flex items-center justify-center rounded-full text-sm font-bold transition-all ${isToday(d) ? 'bg-blue-600 text-white shadow-md shadow-blue-500/30 scale-110' : 'text-slate-800 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'}`}>
                      {d.getDate()}
                    </div>
                  </div>
                ))}
              </div>

              {/* Google Calendar Style Timeline (Percentage Scaled) */}
              <div className="flex-1 flex flex-col bg-white/30 dark:bg-black/10 min-h-0 py-6">
                <div className="flex-1 flex relative">
                  
                  {/* Y-Axis: Time Labels */}
                  <div className="w-[80px] shrink-0 border-r border-slate-200/50 dark:border-slate-800/50 relative bg-white/50 dark:bg-black/20 z-10">
                    {Array.from({ length: totalHours + 1 }).map((_, i) => {
                      const hour = Math.floor(timelineData.minTime / 60) + i;
                      const ampm = hour >= 12 ? 'PM' : 'AM';
                      const displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
                      
                      const topPercent = ((i * 60) / totalMins) * 100;
                      if (topPercent > 100) return null;

                      return (
                        <div key={i} className="absolute w-full text-right pr-3" style={{ top: `${topPercent}%`, transform: 'translateY(-50%)' }}>
                          <span className="text-[10px] font-bold text-slate-500">{displayHour} {ampm}</span>
                        </div>
                      )
                    })}
                  </div>

                  {/* Absolute Positioned Grid */}
                  <div className="flex-1 flex relative">
                    {/* Background Grid Lines (Hours) */}
                    <div className="absolute inset-0 pointer-events-none z-0">
                      {Array.from({ length: totalHours + 1 }).map((_, i) => {
                        const topPercent = ((i * 60) / totalMins) * 100;
                        if (topPercent > 100) return null;
                        return (
                          <div key={i} className="absolute w-full border-b border-slate-200/50 dark:border-slate-800/50" style={{ top: `${topPercent}%` }} />
                        )
                      })}
                    </div>

                    {/* Columns per day */}
                    {renderDays.map((d, colIdx) => {
                      const dateStr = formatDateStr(d);
                      const dayPeriodsRaw = periods.filter(p => p.date === dateStr && selectedSubjects.has(p.subject_id));
                      
                      // Pre-process all valid bounds
                      const plottedPeriods = dayPeriodsRaw.map(p => {
                          let startMins = timeToMinutes(p.start_time);
                          let endMins = timeToMinutes(p.end_time);
                          const isValidDuration = startMins !== null && !isNaN(startMins) && endMins !== null && !isNaN(endMins) && (endMins - startMins >= 15);

                          if (!timelineData.hasValidTimes || !isValidDuration) {
                            const fake = timelineData.slotToFakeTime.get(p.slot);
                            if (fake) {
                              startMins = fake.start;
                              endMins = fake.end;
                            }
                          }
                          return { ...p, startMins, endMins };
                      }).filter(p => p.startMins !== null && p.endMins !== null);

                      // Distribute into overlapping columns
                      const groups: typeof plottedPeriods[] = [];
                      plottedPeriods.forEach(p => {
                          let placed = false;
                          for (const group of groups) {
                              const overlaps = group.some(existing => (p.startMins! < existing.endMins! && p.endMins! > existing.startMins!));
                              if (overlaps) {
                                  group.push(p);
                                  placed = true;
                                  break;
                              }
                          }
                          if (!placed) {
                              groups.push([p]);
                          }
                      });

                      const renderedPeriods: (typeof plottedPeriods[0] & { leftPercent: number, widthPercent: number })[] = [];
                      groups.forEach(group => {
                          group.forEach((p, idx) => {
                              renderedPeriods.push({
                                  ...p,
                                  leftPercent: (100 / group.length) * idx,
                                  widthPercent: 100 / group.length
                              });
                          });
                      });
                      
                      return (
                        <div key={colIdx} className="flex-1 border-r border-slate-200/50 dark:border-slate-800/50 last:border-0 relative hover:z-50 transition-all duration-300">
                          {renderedPeriods.map((p, idx) => {
                            const isGenerated = p.is_generated;
                            const startMins = p.startMins!;
                            const endMins = p.endMins!;

                            // Calculate Percentage Absolute position
                            const topPercent = ((startMins - timelineData.minTime) / totalMins) * 100;
                            const heightPercent = ((endMins - startMins) / totalMins) * 100;
                            
                            const isDimmed = hoveredSubjectId !== null && hoveredSubjectId !== p.subject_id;

                            return (
                              <div 
                                key={idx} 
                                className={`absolute transition-all duration-500 ease-out px-[2px] py-[1px] group ${
                                  isDimmed ? 'opacity-30 grayscale-[0.8] blur-[2px] scale-[0.98] z-0' : 'hover:z-[100] z-10'
                                }`} 
                                style={{ 
                                  top: `${topPercent}%`, 
                                  height: `${heightPercent}%`,
                                  left: `${p.leftPercent}%`,
                                  width: `${p.widthPercent}%`
                                }}
                                onMouseEnter={() => setHoveredSubjectId(p.subject_id)}
                                onMouseLeave={() => setHoveredSubjectId(null)}
                              >
                                <div 
                                  className={`w-full h-full rounded-[6px] flex flex-col justify-center p-1.5 cursor-pointer shadow-sm border overflow-hidden transition-all duration-500 ease-out origin-center group-hover:absolute group-hover:-inset-x-8 group-hover:-top-4 group-hover:-bottom-auto group-hover:h-auto group-hover:min-h-full group-hover:min-w-[220px] group-hover:z-[100] group-hover:scale-[1.05] group-hover:ring-4 group-hover:ring-primary/20 ${
                                    isGenerated 
                                    ? `bg-gradient-to-br ${getSubjectColor(p.subject_id)} text-white border-white/20 shadow-md group-hover:shadow-[0_20px_40px_rgba(0,0,0,0.3)]` 
                                    : `bg-white dark:bg-slate-800 border-dashed border-red-400 dark:border-red-500/50 text-slate-800 dark:text-slate-200 group-hover:shadow-[0_20px_40px_rgba(0,0,0,0.15)]`
                                  }`}
                                >
                                  <div className="flex flex-col items-center group-hover:items-start w-full relative z-10 transition-all duration-500 ease-out">
                                    <span className="text-[10px] font-extrabold leading-tight truncate group-hover:whitespace-normal group-hover:text-clip text-center group-hover:text-left group-hover:text-[13px] transition-all duration-500 w-full">
                                      {p.subject_name}
                                    </span>
                                    
                                    <div className="w-full flex flex-col max-h-0 opacity-0 group-hover:max-h-[300px] group-hover:opacity-100 group-hover:mt-2 transition-all duration-500 ease-out overflow-hidden gap-1.5">
                                      
                                      <div className="flex items-center gap-1.5 text-[10px] font-semibold opacity-90">
                                        <Clock className="w-3 h-3 flex-shrink-0" />
                                        <span>{p.start_time && p.end_time && p.start_time !== "-" ? `${p.start_time} - ${p.end_time}` : '1-Hour Slot'}</span>
                                      </div>

                                      {p.teacher_name && (
                                        <div className="flex items-center gap-1.5 text-[10px] font-medium opacity-80">
                                          <div className="w-3 h-3 rounded-full bg-current opacity-30 flex-shrink-0" />
                                          <span className="truncate">{p.teacher_name}</span>
                                        </div>
                                      )}

                                      {isGenerated && p.chapter_name && (
                                        <div className="flex flex-col mt-1.5 pt-1.5 border-t border-current/20 gap-1.5">
                                           <span className="text-[8px] font-bold uppercase tracking-wider opacity-70">Generated Lesson Plan</span>
                                           <span className="text-[11px] font-bold leading-tight">{p.chapter_name}</span>
                                           {p.primary_concept_name && (
                                             <span className="text-[10px] font-medium opacity-90 leading-tight flex items-start gap-1">
                                                <BrainCircuit className="w-3 h-3 flex-shrink-0 mt-[1px]" />
                                                <span className="flex-1">{p.primary_concept_name}</span>
                                             </span>
                                           )}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            </div>
            );
          })()}

          {/* MONTH VIEW */}
          {viewMode === "month" && (
            <div className="w-full flex-1 flex flex-col bg-white/40 dark:bg-black/20 backdrop-blur-2xl rounded-[2rem] border border-white/40 dark:border-white/5 shadow-xl overflow-hidden min-h-0">
              
              {/* Day of Week Headers */}
              <div className="grid grid-cols-7 border-b border-slate-200/50 dark:border-slate-800/50 shrink-0 bg-white/30 dark:bg-black/10">
                {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(day => (
                  <div key={day} className="py-3 text-center border-r border-slate-200/50 dark:border-slate-800/50 last:border-0 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    {day}
                  </div>
                ))}
              </div>

              {/* Month Grid */}
              <div className="flex-1 grid grid-cols-7 grid-rows-6 min-h-0 bg-slate-50/50 dark:bg-[#0a0a0a]/50">
                {monthDays.map((d, i) => {
                  const isCurrentMonth = d.getMonth() === currentDate.getMonth();
                  const dateStr = formatDateStr(d);
                  
                  // In month view, we want to list all actual periods and sort by start time
                  const dayPeriods = periods.filter(p => p.date === dateStr && selectedSubjects.has(p.subject_id));
                  
                  // Sort them chronologically
                  dayPeriods.sort((a, b) => {
                     const timeA = timeToMinutes(a.start_time) || 0;
                     const timeB = timeToMinutes(b.start_time) || 0;
                     return timeA - timeB;
                  });

                  const isExpanded = expandedDay === dateStr;
                  const displaySubjects = isExpanded ? dayPeriods : dayPeriods.slice(0, 2);
                  const hiddenCount = dayPeriods.length - 2;

                  const isBottomRow = i >= 28;
                  const isRightEdge = i % 7 >= 5;
                  const popoverY = isBottomRow ? 'bottom-[-10px]' : 'top-[-10px]';
                  const popoverX = isRightEdge ? 'right-[-10px]' : 'left-[-10px]';

                  return (
                    <div 
                      key={i} 
                      className={`relative border-r border-b border-slate-200/50 dark:border-slate-800/50 flex flex-col p-1 transition-colors min-h-0 ${
                        isCurrentMonth ? 'bg-white/40 dark:bg-black/20' : 'bg-slate-100/30 dark:bg-slate-900/10'
                      } ${isExpanded ? 'z-[200]' : 'hover:z-50'}`}
                    >
                      <div className="flex justify-between items-start mb-[2px] px-0.5 shrink-0">
                        <span className={`w-5 h-5 flex items-center justify-center rounded-full text-[10px] font-bold transition-all ${
                          isToday(d) ? 'bg-blue-600 text-white shadow-md' : 
                          isCurrentMonth ? 'text-slate-700 dark:text-slate-300' : 'text-slate-400 dark:text-slate-600'
                        }`}>
                          {d.getDate()}
                        </span>
                      </div>
                      
                      {/* Event Chips Container */}
                      <div className="flex-1 flex flex-col gap-[1px] min-h-0 overflow-hidden">
                        {displaySubjects.map((p, idx) => {
                          const isDimmed = hoveredSubjectId !== null && hoveredSubjectId !== p.subject_id;
                          return (
                            <div
                              key={idx}
                              onMouseEnter={() => setHoveredSubjectId(p.subject_id)}
                              onMouseLeave={() => setHoveredSubjectId(null)}
                              className={`px-1.5 py-[2px] rounded-[3px] text-[9px] font-bold leading-tight truncate transition-all duration-300 cursor-pointer shrink-0 ${
                                isDimmed ? 'opacity-30 grayscale-[0.8] blur-[1px]' : 'hover:scale-[1.02] shadow-sm z-10'
                              } ${
                                p.is_generated 
                                ? `bg-gradient-to-r ${getSubjectColor(p.subject_id)} text-white`
                                : `bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300`
                              }`}
                              title={p.subject_name}
                            >
                              {p.subject_name}
                            </div>
                          );
                        })}

                        {!isExpanded && hiddenCount > 0 && (
                          <div 
                            onClick={() => setExpandedDay(dateStr)}
                            className="px-1.5 py-[1px] text-[9px] font-bold text-slate-500 hover:text-blue-600 dark:text-slate-400 dark:hover:text-blue-400 cursor-pointer mt-[1px] hover:bg-black/5 dark:hover:bg-white/5 rounded transition-colors w-max shrink-0"
                          >
                            +{hiddenCount} more
                          </div>
                        )}
                      </div>

                      {/* Expanded Popover */}
                      {isExpanded && (
                         <>
                           <div className="fixed inset-0 z-[190]" onClick={() => setExpandedDay(null)} />
                           <div className={`absolute ${popoverY} ${popoverX} w-[150%] min-w-[180px] max-h-[300px] overflow-y-auto no-scrollbar z-[200] bg-white/95 dark:bg-[#111111]/95 backdrop-blur-xl shadow-[0_20px_40px_rgba(0,0,0,0.3)] border border-black/10 dark:border-white/10 rounded-xl p-3 flex flex-col gap-1.5 animate-in fade-in zoom-in-95 duration-200 origin-top-left`}>
                              <div className="flex justify-between items-center mb-1 border-b border-black/5 dark:border-white/5 pb-2">
                                 <div className="flex flex-col">
                                   <span className="text-xs font-bold text-slate-700 dark:text-slate-300 ml-1 leading-none">{d.toLocaleDateString('en-US', { weekday: 'short' })}</span>
                                   <span className="text-[17px] font-extrabold text-blue-600 dark:text-blue-400 ml-1 leading-tight">{d.getDate()}</span>
                                 </div>
                                 <button onClick={() => setExpandedDay(null)} className="w-6 h-6 flex items-center justify-center rounded-full hover:bg-black/10 dark:hover:bg-white/10 text-slate-500 transition-colors">✕</button>
                              </div>
                              {dayPeriods.map((p, idx) => {
                                const isDimmed = hoveredSubjectId !== null && hoveredSubjectId !== p.subject_id;
                                return (
                                  <div
                                    key={`expanded-${idx}`}
                                    onMouseEnter={() => setHoveredSubjectId(p.subject_id)}
                                    onMouseLeave={() => setHoveredSubjectId(null)}
                                    className={`px-2 py-1.5 rounded-[6px] text-[10px] font-bold leading-tight truncate transition-all duration-300 cursor-pointer flex items-center justify-between ${
                                      isDimmed ? 'opacity-30 grayscale-[0.8] blur-[1px]' : 'hover:scale-[1.02] shadow-sm z-10'
                                    } ${
                                      p.is_generated 
                                      ? `bg-gradient-to-r ${getSubjectColor(p.subject_id)} text-white`
                                      : `bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300`
                                    }`}
                                  >
                                    <span className="truncate mr-2">{p.subject_name}</span>
                                    {p.start_time && p.start_time !== "-" && (
                                      <span className="text-[9px] opacity-80 font-medium whitespace-nowrap">{p.start_time}</span>
                                    )}
                                  </div>
                                );
                              })}
                           </div>
                         </>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
      {/* END INNER WRAPPER */}
    </div>
  );
}
