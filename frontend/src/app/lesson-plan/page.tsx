"use client";

import { useState, useEffect } from "react";
import { BookOpen, Calendar, Clock, ChevronRight, CheckCircle2, PlayCircle, Layers, FileText, ArrowLeft, Download, User, LayoutGrid, List, X, Wand2 } from "lucide-react";
import { CustomSelect } from "@/components/ui/custom-select";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";
import * as XLSX from "xlsx";

export default function LessonPlanDashboard() {
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0); // 0: Config, 1: Loading, 2: Dashboard
  const [viewMode, setViewMode] = useState<"list" | "calendar">("calendar");
  const [currentDate, setCurrentDate] = useState<Date>(new Date());

  // Form State
  const [instId, setInstId] = useState("");
  const [stdId, setStdId] = useState("");
  const [divId, setDivId] = useState("");
  const [subId, setSubId] = useState("");
  const [year, setYear] = useState("");

  const [teacherModalData, setTeacherModalData] = useState<any>(null);
  const [teacherAssignments, setTeacherAssignments] = useState<any>({});

  // Dropdowns state
  const [institutes, setInstitutes] = useState<any[]>([]);
  const [filteredStandards, setFilteredStandards] = useState<any[]>([]);
  const [filteredDivisions, setFilteredDivisions] = useState<any[]>([]);
  const [filteredSubjects, setFilteredSubjects] = useState<any[]>([]);
  const [filteredYears, setFilteredYears] = useState<number[]>([]);
  const [dropdownLoading, setDropdownLoading] = useState(false);

  // Fetch institutes on mount
  useEffect(() => {
    fetch("http://localhost:8000/lesson-intelligence/dropdowns")
      .then(res => res.json())
      .then(data => {
        if (data.status === "success") {
          setInstitutes(data.institutes || []);
        }
      })
      .catch(console.error);
  }, []);

  // When institute changes, fetch valid standards/subjects/years
  const handleInstituteChange = async (newInstId: string) => {
    setInstId(newInstId);
    setStdId("");
    setDivId("");
    setSubId("");
    setYear("");
    setFilteredStandards([]);
    setFilteredDivisions([]);
    setFilteredSubjects([]);
    setFilteredYears([]);

    if (!newInstId) return;

    setDropdownLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/dropdowns/filter?sub_institute_id=${newInstId}`);
      const data = await res.json();
      if (data.status === "success") {
        setFilteredStandards(data.standards || []);
        // Subjects and Years will populate when standard/subject are selected.
      }
    } catch (err) {
      console.error("Failed to load filtered options:", err);
    } finally {
      setDropdownLoading(false);
    }
  };

  const handleStandardChange = async (newStdId: string) => {
    setStdId(newStdId);
    setDivId("");
    setSubId("");
    setYear("");
    setFilteredDivisions([]);
    setFilteredSubjects([]);
    setFilteredYears([]);

    if (!newStdId || !instId) return;

    setDropdownLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/dropdowns/filter?sub_institute_id=${instId}&standard_id=${newStdId}`);
      const data = await res.json();
      if (data.status === "success") {
        setFilteredDivisions(data.divisions || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setDropdownLoading(false);
    }
  };

  const handleDivisionChange = async (newDivId: string) => {
    setDivId(newDivId);
    setSubId("");
    setYear("");
    setFilteredSubjects([]);
    setFilteredYears([]);

    if (!newDivId || !instId || !stdId) return;

    setDropdownLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/dropdowns/filter?sub_institute_id=${instId}&standard_id=${stdId}&division_id=${newDivId}`);
      const data = await res.json();
      if (data.status === "success") {
        setFilteredSubjects(data.subjects || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setDropdownLoading(false);
    }
  };

  const handleSubjectChange = async (newSubId: string) => {
    setSubId(newSubId);
    setYear("");
    setFilteredYears([]);

    if (!newSubId || !instId || !stdId || !divId) return;

    setDropdownLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/dropdowns/filter?sub_institute_id=${instId}&standard_id=${stdId}&division_id=${divId}&subject_id=${newSubId}`);
      const data = await res.json();
      if (data.status === "success") {
        setFilteredYears(data.years || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setDropdownLoading(false);
    }
  };

  // Data State
  const [macroPlans, setMacroPlans] = useState<any[]>([]);
  const [activePlan, setActivePlan] = useState<any | null>(null);
  const [periods, setPeriods] = useState<any[]>([]);
  const [selectedPeriod, setSelectedPeriod] = useState<any | null>(null);
  const [holidays, setHolidays] = useState<any[]>([]);
  const [exams, setExams] = useState<any[]>([]);

  // Calendar derived states
  useEffect(() => {
    if (periods.length > 0) {
      const minDateStr = periods.map((p: any) => p.scheduled_date).sort()[0];
      if (minDateStr) {
        const earliestDate = new Date(minDateStr);
        // Only set if current date is not already initialized properly
        if (currentDate.getFullYear() === new Date().getFullYear() && currentDate.getMonth() === new Date().getMonth()) {
          setCurrentDate(new Date(earliestDate.getFullYear(), earliestDate.getMonth(), 1));
        }
      }
    }
  }, [periods]);

  const getDaysInMonth = (date: Date) => {
    const year = date.getFullYear();
    const month = date.getMonth();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstDayOfMonth = new Date(year, month, 1).getDay(); // 0 is Sunday
    
    // We want Monday = 0, Sunday = 6 for our grid
    const startingBlankDays = firstDayOfMonth === 0 ? 6 : firstDayOfMonth - 1;
    
    const days = [];
    for (let i = 0; i < startingBlankDays; i++) {
      days.push(null);
    }
    for (let i = 1; i <= daysInMonth; i++) {
      const d = new Date(year, month, i);
      const dateString = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      days.push({ dayNumber: i, dateString });
    }
    return days;
  };

  const calendarDays = getDaysInMonth(currentDate);
  const weekDayHeaders = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  let minMonthDate: Date | null = null;
  let maxMonthDate: Date | null = null;

  if (activePlan?.term_start_date && activePlan?.term_end_date) {
    const start = new Date(activePlan.term_start_date);
    const end = new Date(activePlan.term_end_date);
    minMonthDate = new Date(start.getFullYear(), start.getMonth(), 1);
    maxMonthDate = new Date(end.getFullYear(), end.getMonth(), 1);
  } else if (periods.length > 0) {
    const dates = periods.map(p => p.scheduled_date).sort();
    if (dates.length > 0) {
      const start = new Date(dates[0]);
      const end = new Date(dates[dates.length - 1]);
      minMonthDate = new Date(start.getFullYear(), start.getMonth(), 1);
      maxMonthDate = new Date(end.getFullYear(), end.getMonth(), 1);
    }
  }

  const prevMonthDate = new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1);
  const nextMonthDate = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1);

  const canGoPrev = minMonthDate ? prevMonthDate.getTime() >= minMonthDate.getTime() : true;
  const canGoNext = maxMonthDate ? nextMonthDate.getTime() <= maxMonthDate.getTime() : true;

  const prevMonth = () => {
    if (canGoPrev) setCurrentDate(prevMonthDate);
  };
  const nextMonth = () => {
    if (canGoNext) setCurrentDate(nextMonthDate);
  };

  // 1. Fetch Macro Plan
  const fetchMacroPlan = async (forceGenerate = false) => {
    setLoading(true);
    setStep(1);
    try {
      if (forceGenerate) {
        const genRes = await fetch("http://localhost:8000/lesson-intelligence/macro-plan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sub_institute_id: parseInt(instId),
            standard_id: parseInt(stdId),
            division_id: parseInt(divId),
            subject_id: parseInt(subId),
            syear: parseInt(year)
          })
        });
        if (!genRes.ok) {
          const errData = await genRes.json();
          throw new Error(errData.detail || "Failed to generate macro plan");
        }
      }

      const res = await fetch(
        `http://localhost:8000/lesson-intelligence/macro-plan/${instId}/${stdId}/${subId}?syear=${year}&division_id=${divId}`
      );

      if (!res.ok) {
        if (res.status === 404 && !forceGenerate) {
          // Ask to generate
          if (confirm("No macro plan found. Generate one now?")) {
            await fetchMacroPlan(true);
            return;
          } else {
            setStep(0);
            return;
          }
        }
        throw new Error("Failed to fetch macro plan");
      }

      const data = await res.json();
      setMacroPlans(data.plans || []);

      if (data.plans?.length > 0) {
        await selectPlan(data.plans[0]);
      }
      setStep(2);
    } catch (err: any) {
      console.error(err);
      alert(err.message || "Error fetching macro plan");
      setStep(0);
    } finally {
      setLoading(false);
    }
  };

  // 2. Select Plan & Fetch Periods
  const selectPlan = async (plan: any) => {
    setActivePlan(plan);
    setLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/meso-plan/${plan.id}/periods`);
      if (res.ok) {
        const data = await res.json();
        setPeriods(data.periods || []);
      }

      // Fetch Holidays and Exams
      const evRes = await fetch(`http://localhost:8000/lesson-intelligence/calendar-events/${plan.sub_institute_id}/${plan.standard_id}/${plan.subject_id}?syear=${plan.syear}`);
      if (evRes.ok) {
        const evData = await evRes.json();
        setHolidays(evData.holidays || []);
        setExams(evData.exams || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // 3. Generate Meso Plan
  const checkAndGenerateMesoPlan = async () => {
    if (!activePlan) return;
    setLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/meso-plan/${activePlan.id}/teachers`);
      if (res.ok) {
        const data = await res.json();
        if (data.teachers && data.teachers.length >= 1) {
          setTeacherModalData(data);
          const initial: any = {};
          data.teachers.forEach((t: any) => initial[t.id] = []);
          setTeacherAssignments(initial);
        } else {
          await executeMesoPlan();
        }
      } else {
        await executeMesoPlan();
      }
    } catch (err) {
      console.error(err);
      await executeMesoPlan();
    } finally {
      setLoading(false);
    }
  };

  const executeMesoPlan = async (assignments: any = null) => {
    if (!activePlan) return;
    setTeacherModalData(null);
    setLoading(true);
    try {
      const body = assignments ? JSON.stringify({ teacher_assignments: assignments }) : undefined;
      const res = await fetch(`http://localhost:8000/lesson-intelligence/meso-plan/${activePlan.id}`, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body
      });
      if (res.ok) {
        await selectPlan(activePlan); // Refresh periods
      } else {
        alert("Failed to generate meso plan");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // 4. Generate Micro Plan
  const generateMicroPlan = async (periodId: number) => {
    setLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/lesson-intelligence/micro-plan/period/${periodId}`, {
        method: "POST"
      });
      if (res.ok) {
        await selectPlan(activePlan); // Refresh single period is better, but this is fine for now
      } else {
        alert("Failed to generate micro plan");
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // 5. Export to PDF
  const exportToPDF = () => {
    if (!activePlan || !periods.length) return;
    const doc = new jsPDF("landscape");
    doc.setFontSize(16);
    doc.text(`Lesson Plan: ${activePlan.plan_title}`, 14, 15);
    doc.setFontSize(10);
    doc.text(`Total Periods: ${activePlan.total_periods} | Duration: ${activePlan.period_duration_min} min/period`, 14, 22);

    const tableData = periods.map(p => [
      new Date(p.scheduled_date).toLocaleDateString(),
      `${p.week_day} ${p.period_slot}`,
      p.period_type,
      p.teacher_name || "-",
      p.chapter_name || "-",
      p.primary_concept_name || "-",
      p.plan_json ? "Generated" : "Pending",
      p.plan_json ? `${p.plan_json.warm_up?.duration_min}m Warm, ${p.plan_json.core_teaching?.duration_min}m Core, ${p.plan_json.activity?.duration_min}m Act, ${p.plan_json.wrap_up?.duration_min}m Wrap` : "-"
    ]);

    autoTable(doc, {
      startY: 30,
      head: [["Date", "Slot", "Type", "Teacher", "Chapter", "Concept", "Status", "Duration Breakdown"]],
      body: tableData,
      theme: "grid",
      headStyles: { fillColor: [59, 130, 246] },
      styles: { fontSize: 8 }
    });

    doc.save(`Lesson_Plan_${activePlan.id}.pdf`);
  };

  // 6. Export to Excel
  const exportToExcel = () => {
    if (!activePlan || !periods.length) return;
    
    const excelData = periods.map(p => ({
      "Date": new Date(p.scheduled_date).toLocaleDateString(),
      "Day": p.week_day,
      "Slot": p.period_slot,
      "Type": p.period_type,
      "Teacher": p.teacher_name || "-",
      "Chapter": p.chapter_name || "-",
      "Primary Concept": p.primary_concept_name || "-",
      "Status": p.plan_json ? "Generated" : "Pending",
      "Warm Up (min)": p.plan_json?.warm_up?.duration_min || "",
      "Core Teaching (min)": p.plan_json?.core_teaching?.duration_min || "",
      "Activity (min)": p.plan_json?.activity?.duration_min || "",
      "Wrap Up (min)": p.plan_json?.wrap_up?.duration_min || "",
      "Blooms Level": p.blooms_level || "",
      "Pedagogy": p.pedagogy_method || ""
    }));

    const worksheet = XLSX.utils.json_to_sheet(excelData);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Lesson Plan");
    XLSX.writeFile(workbook, `Lesson_Plan_${activePlan.id}.xlsx`);
  };

  return (
    <div className="flex h-[100dvh] max-h-[100dvh] flex-col bg-background relative overflow-hidden">
      {/* iOS Liquid Glass Background */}
      <div className="absolute top-[-15%] left-[-10%] w-[50%] h-[50%] rounded-[100%] bg-blue-500/30 dark:bg-blue-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] rounded-[100%] bg-purple-500/30 dark:bg-purple-600/20 blur-[140px] mix-blend-normal opacity-80 pointer-events-none animate-pulse" style={{ animationDelay: '2s' }} />
      <div className="absolute top-[20%] right-[10%] w-[30%] h-[30%] rounded-[100%] bg-pink-500/20 dark:bg-pink-600/20 blur-[120px] mix-blend-normal opacity-60 pointer-events-none animate-pulse" style={{ animationDelay: '4s' }} />

      {/* Header matching extraction UI */}
      <header className="fixed top-4 left-1/2 -translate-x-1/2 z-50 w-[96%] max-w-[1600px] rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] px-5 py-2.5 transition-all hover:bg-white/50 dark:hover:bg-black/50 overflow-hidden before:absolute before:inset-0 before:-z-10 before:rounded-full before:bg-gradient-to-br before:from-white/40 before:to-transparent before:opacity-50 dark:before:from-white/10 dark:before:to-transparent">
        <div className="flex h-10 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 shadow-inner border-[0.5px] border-primary/20">
              <BookOpen className="h-4 w-4 text-primary" />
            </div>
            <span className="text-[17px] font-semibold tracking-tight text-foreground/90">
              LESSON PLANNER
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

      <main className="relative z-10 w-full h-full pt-28 px-6 pb-6 flex flex-col items-center">

        {/* Step 0: Config Form */}
        {step === 0 && (
          <div className="w-full max-w-lg bg-white/50 dark:bg-black/50 backdrop-blur-3xl border border-black/10 dark:border-white/10 rounded-3xl p-8 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] mt-10">
            <h2 className="text-2xl font-bold mb-8 text-center text-foreground">Load School Schedule</h2>
            <div className="space-y-5">
              <div className="relative z-[60]">
                <label className="text-xs font-medium text-foreground/80 pl-1 mb-1.5 block">Institute</label>
                <CustomSelect
                  value={instId}
                  onChange={handleInstituteChange}
                  options={institutes.map(inst => ({ label: inst.name, value: inst.id.toString() }))}
                  placeholder="Select Institute..."
                />
              </div>

              <div className="relative z-[50]">
                <label className="text-xs font-medium text-foreground/80 pl-1 mb-1.5 block">Standard (Class)</label>
                <CustomSelect
                  value={stdId}
                  onChange={handleStandardChange}
                  options={filteredStandards.map(std => ({ label: std.name, value: std.id.toString() }))}
                  placeholder={dropdownLoading ? "Loading..." : instId ? "Select Standard..." : "Select Institute first"}
                />
              </div>

              <div className="relative z-[45]">
                <label className="text-xs font-medium text-foreground/80 pl-1 mb-1.5 block">Division (Section)</label>
                <CustomSelect
                  value={divId}
                  onChange={handleDivisionChange}
                  options={filteredDivisions.map(div => ({ label: div.name, value: div.id.toString() }))}
                  placeholder={dropdownLoading ? "Loading..." : stdId ? "Select Division..." : "Select Standard first"}
                />
              </div>

              <div className="relative z-[40]">
                <label className="text-xs font-medium text-foreground/80 pl-1 mb-1.5 block">Subject</label>
                <CustomSelect
                  value={subId}
                  onChange={handleSubjectChange}
                  options={filteredSubjects.map(sub => ({ label: sub.name, value: sub.id.toString() }))}
                  placeholder={dropdownLoading ? "Loading..." : divId ? "Select Subject..." : "Select Division first"}
                />
              </div>

              <div className="relative z-[30]">
                <label className="text-xs font-medium text-foreground/80 pl-1 mb-1.5 block">Academic Year</label>
                <CustomSelect
                  value={year}
                  onChange={setYear}
                  options={filteredYears.map(y => ({ label: y.toString(), value: y.toString() }))}
                  placeholder={dropdownLoading ? "Loading..." : instId ? "Select Year..." : "Select Institute first"}
                />
              </div>

              <button
                onClick={() => fetchMacroPlan(false)}
                disabled={!instId || !stdId || !divId || !subId || !year}
                className={`w-full mt-6 py-3.5 rounded-full border-[0.5px] border-black/10 dark:border-white/20 bg-white/40 dark:bg-black/40 backdrop-blur-[40px] saturate-200 shadow-[0_8px_32px_0_rgba(0,0,0,0.1)] text-foreground font-semibold transition-all flex items-center justify-center gap-2 ${
                  !instId || !stdId || !divId || !subId || !year
                    ? 'opacity-50 cursor-not-allowed'
                    : 'hover:scale-[1.02] hover:bg-white/60 dark:hover:bg-black/60'
                }`}
              >
                <BookOpen className="h-4 w-4 text-blue-500" /> Fetch Dashboard
              </button>
            </div>
          </div>
        )}

        {/* Step 1: Loading */}
        {loading && (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/50 backdrop-blur-sm">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
          </div>
        )}

        {/* Step 2: Dashboard View */}
        {step === 2 && (
          <div className="w-full max-w-7xl h-full flex flex-col gap-6 overflow-hidden">

            {/* Term Tabs */}
            <div className="flex gap-4 p-2 bg-white/30 dark:bg-black/30 backdrop-blur-xl rounded-2xl border border-black/5 dark:border-white/5 shrink-0">
              {macroPlans.map((plan: any) => (
                <button
                  key={plan.id}
                  onClick={() => selectPlan(plan)}
                  className={`px-6 py-3 rounded-full font-medium transition-all ${activePlan?.id === plan.id ? 'bg-white dark:bg-white/10 shadow text-blue-600 dark:text-blue-400' : 'text-muted-foreground hover:bg-white/50 dark:hover:bg-black/50'}`}
                >
                  {plan.plan_title}
                </button>
              ))}
            </div>

            {/* Main Content Area */}
            {activePlan && (
              <div className="flex-1 flex gap-6 min-h-0">

                {/* Left: Metadata */}
                <div className="w-80 shrink-0 bg-white/50 dark:bg-black/50 backdrop-blur-2xl border border-black/10 dark:border-white/10 rounded-3xl p-6 flex flex-col gap-6 overflow-y-auto">
                  <div>
                    <h3 className="font-bold text-lg">{activePlan.plan_title}</h3>
                    <p className="text-sm text-muted-foreground">Status: {activePlan.generation_status}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 bg-white dark:bg-black/20 rounded-xl border border-black/10 dark:border-white/10 shadow-sm">
                      <div className="text-2xl font-bold text-blue-600">{activePlan.total_periods}</div>
                      <div className="text-xs text-muted-foreground font-medium mt-1">Total Periods</div>
                    </div>
                    <div className="p-4 bg-white dark:bg-black/20 rounded-xl border border-black/10 dark:border-white/10 shadow-sm">
                      <div className="text-2xl font-bold text-blue-600">{activePlan.periods_per_week}</div>
                      <div className="text-xs text-muted-foreground font-medium mt-1">Periods/Week</div>
                    </div>
                    <div className="p-4 bg-white dark:bg-black/20 rounded-xl border border-black/10 dark:border-white/10 shadow-sm">
                      <div className="text-2xl font-bold text-blue-600">{activePlan.period_duration_min}m</div>
                      <div className="text-xs text-muted-foreground font-medium mt-1">Duration</div>
                    </div>
                    <div className="p-4 bg-white dark:bg-black/20 rounded-xl border border-black/10 dark:border-white/10 shadow-sm">
                      <div className="text-2xl font-bold text-blue-600">{activePlan.holidays_count}</div>
                      <div className="text-xs text-muted-foreground font-medium mt-1">Holidays Excl.</div>
                    </div>
                  </div>

                  {periods.length === 0 && (
                    <div className="mt-auto">
                      <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-2xl mb-4">
                        <p className="text-sm text-yellow-700 dark:text-yellow-400">
                          Meso Plan (Physical Periods) not generated yet.
                        </p>
                      </div>
                      <button
                        onClick={checkAndGenerateMesoPlan}
                        className="w-full py-2.5 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 transition shadow-sm"
                      >
                        Generate Meso Plan
                      </button>
                    </div>
                  )}
                </div>

                {/* Right: Periods Month Calendar */}
                <div className="flex-1 bg-white/50 dark:bg-black/50 backdrop-blur-2xl border border-black/10 dark:border-white/10 rounded-3xl p-6 flex flex-col min-h-0">
                  <div className="flex items-center justify-between mb-6 shrink-0 flex-wrap gap-4">
                    <div className="flex items-center gap-3">
                      <h2 className="text-xl font-bold flex items-center gap-2">
                        <Calendar className="h-5 w-5" />
                        Teacher Schedule (Month View)
                      </h2>
                      <span className="text-sm font-medium bg-blue-500/10 text-blue-600 px-3 py-1 rounded-full border border-blue-500/20">
                        {periods.length} Periods
                      </span>
                    </div>

                    <div className="flex items-center gap-3">
                      <button
                        onClick={exportToPDF}
                        disabled={periods.length === 0}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-red-500/10 text-red-600 border border-red-500/20 text-sm font-medium hover:bg-red-500/20 transition-all disabled:opacity-50"
                      >
                        <FileText className="h-4 w-4" /> PDF
                      </button>
                      <button
                        onClick={exportToExcel}
                        disabled={periods.length === 0}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-500/10 text-emerald-600 border border-emerald-500/20 text-sm font-medium hover:bg-emerald-500/20 transition-all disabled:opacity-50"
                      >
                        <Download className="h-4 w-4" /> Excel
                      </button>
                    </div>
                  </div>

                  <div className="flex-1 flex flex-col bg-white dark:bg-black/20 rounded-2xl border border-black/10 dark:border-white/10 overflow-hidden shadow-sm">
                    {periods.length === 0 ? (
                      <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
                        <Calendar className="h-12 w-12 mb-4 opacity-20" />
                        <p>No periods to display.</p>
                      </div>
                    ) : (
                      <>
                        {/* Calendar Header */}
                        <div className="flex items-center justify-between p-4 border-b border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5">
                          <button onClick={prevMonth} disabled={!canGoPrev} className="p-2 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition disabled:opacity-30 disabled:hover:bg-transparent">
                            <ArrowLeft className="h-5 w-5" />
                          </button>
                          <h3 className="font-bold text-xl uppercase tracking-widest text-blue-900 dark:text-blue-100">
                            {currentDate.toLocaleString('default', { month: 'long', year: 'numeric' })}
                          </h3>
                          <button onClick={nextMonth} disabled={!canGoNext} className="p-2 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition disabled:opacity-30 disabled:hover:bg-transparent">
                            <ChevronRight className="h-5 w-5" />
                          </button>
                        </div>
                        
                        {/* Days Header */}
                        <div className="grid grid-cols-7 border-b border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5 shrink-0">
                          {weekDayHeaders.map(d => (
                            <div key={d} className="p-3 text-center font-bold text-xs uppercase tracking-wider text-muted-foreground">{d}</div>
                          ))}
                        </div>

                        {/* Calendar Grid */}
                        <div className="flex-1 grid grid-cols-7 auto-rows-[minmax(160px,auto)] overflow-y-auto bg-black/[0.02] dark:bg-white/[0.02]">
                          {calendarDays.map((day, idx) => {
                            if (!day) return <div key={`empty-${idx}`} className="border-b border-r border-black/5 dark:border-white/5 bg-transparent" />;
                            
                            const dayPeriods = periods.filter((p: any) => p.scheduled_date === day.dateString).sort((a: any, b: any) => a.period_slot.localeCompare(b.period_slot));
                            const dObj = new Date(day.dateString);
                            const isWeekend = dObj.getDay() === 0;
                            
                            const dayHoliday = holidays.find(h => h.date === day.dateString);
                            const dayExams = exams.filter(e => e.date === day.dateString);
                            
                            const hasExams = dayExams.length > 0;

                            return (
                              <div key={day.dateString} className={`border-b border-r border-black/5 dark:border-white/5 flex flex-col p-1.5 min-h-[160px] transition-colors hover:bg-black/5 dark:hover:bg-white/5 relative group ${isWeekend ? 'bg-black/[0.03] dark:bg-white/[0.02]' : hasExams ? 'bg-orange-50/30 dark:bg-orange-950/20' : 'bg-white dark:bg-transparent'}`}>
                                {/* Date Number */}
                                <div className={`text-xs font-semibold w-6 h-6 rounded-full flex items-center justify-center mb-1 ml-1 ${dayHoliday ? 'text-red-600 dark:text-red-400' : hasExams ? 'text-orange-600 dark:text-orange-400' : isWeekend ? 'text-muted-foreground' : 'text-foreground'}`}>
                                  {day.dayNumber}
                                </div>
                                
                                {/* Periods Stack */}
                                <div className="flex flex-col gap-1 flex-1">
                                  {dayPeriods.length > 0 ? (
                                    dayPeriods.map((p: any) => (
                                      <div key={p.id} className="relative h-[28px] w-full group/card cursor-pointer" onClick={() => { if (p.plan_json) setSelectedPeriod(p); }}>
                                        <div 
                                          className={`absolute top-0 ${[0, 5, 6].includes(dObj.getDay()) ? 'right-0 origin-top-right group-hover/card:-right-2' : 'left-0 origin-top-left group-hover/card:-left-2'} z-10 group-hover/card:z-50 border rounded-md transition-all duration-200 flex flex-col overflow-hidden bg-white dark:bg-slate-900 
                                            group-hover/card:w-[260px] group-hover/card:h-auto group-hover/card:shadow-2xl group-hover/card:border-blue-400 dark:group-hover/card:border-blue-600
                                            w-full h-[28px] ${p.plan_json ? 'bg-blue-50/80 dark:bg-blue-900/20 border-blue-200/60 dark:border-blue-800/40' : 'bg-black/5 dark:bg-white/5 border-black/10 dark:border-white/10'}`}
                                        >
                                          {/* Always visible header row */}
                                          <div className="flex justify-between items-center px-1.5 h-[26px] shrink-0">
                                            <div className="flex items-center gap-1.5 overflow-hidden">
                                              <span className={`text-[10px] font-bold shrink-0 ${p.plan_json ? 'text-blue-700 dark:text-blue-400' : 'text-muted-foreground'}`}>{p.period_slot}</span>
                                              <span className="text-[10px] font-medium truncate text-slate-600 dark:text-slate-400 group-hover/card:hidden">
                                                {p.teacher_name ? <span className="font-bold text-slate-700 dark:text-slate-300 mr-1">{p.teacher_name}:</span> : null}
                                                {p.chapter_name || "Buffer"}
                                              </span>
                                            </div>
                                            <div className="shrink-0 flex items-center ml-1">
                                              {!p.plan_json ? (
                                                <button 
                                                  onClick={(e) => { e.stopPropagation(); generateMicroPlan(p.id); }} 
                                                  className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-200 transition" 
                                                  title="Generate AI Plan"
                                                >
                                                  <PlayCircle className="h-3.5 w-3.5" />
                                                </button>
                                              ) : (
                                                <CheckCircle2 className="h-3 w-3 text-green-500" />
                                              )}
                                            </div>
                                          </div>

                                          {/* Expanded Details (visible on hover via height auto) */}
                                          <div className="hidden group-hover/card:flex flex-col gap-2 p-3 pt-2 border-t border-slate-100 dark:border-slate-800/60 bg-white dark:bg-slate-900">
                                            <div className="flex justify-between items-center mb-1">
                                              <span className="text-[10px] font-bold bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 px-2 py-0.5 rounded-full">Lecture: {p.period_slot}</span>
                                              {p.start_time && p.end_time && (
                                                <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1 whitespace-nowrap">
                                                  <Clock className="h-3 w-3" />
                                                  {p.start_time} - {p.end_time}
                                                </span>
                                              )}
                                            </div>
                                            
                                            <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2">
                                              <span className="text-[9px] uppercase tracking-wider text-slate-400 font-bold block mb-0.5">Chapter Name</span>
                                              <span className="text-xs font-bold text-slate-800 dark:text-slate-200 leading-tight block">{p.chapter_name || "Buffer Period"}</span>
                                            </div>
                                            
                                            {p.primary_concept_name && (
                                              <div className="bg-slate-50 dark:bg-slate-800/50 rounded p-2">
                                                <span className="text-[9px] uppercase tracking-wider text-slate-400 font-bold block mb-0.5">Concept Name</span>
                                                <span className="text-xs font-medium text-slate-700 dark:text-slate-300 leading-tight block">{p.primary_concept_name}</span>
                                              </div>
                                            )}
                                            
                                            {p.teacher_name && (
                                              <div className="mt-1 flex items-center gap-2">
                                                <div className="w-5 h-5 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-[10px]">👨‍🏫</div>
                                                <div className="flex flex-col">
                                                  <span className="text-[9px] uppercase tracking-wider text-slate-400 font-bold leading-none">Teacher Name</span>
                                                  <span className="text-xs font-medium text-slate-700 dark:text-slate-300 leading-tight mt-0.5">{p.teacher_name}</span>
                                                </div>
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                      </div>
                                    ))
                                  ) : null}
                                  
                                  {hasExams && dayExams.map((exam, i) => (
                                    <div key={`exam-${i}`} className="bg-orange-100 dark:bg-orange-900/40 border border-orange-200 dark:border-orange-800/50 rounded-md p-1.5 flex flex-col gap-0.5 mt-1">
                                      <span className="text-[10px] font-bold text-orange-700 dark:text-orange-400 uppercase tracking-wide">
                                        EXAM
                                      </span>
                                      <span className="text-xs font-bold text-orange-900 dark:text-orange-200 line-clamp-2 leading-tight">
                                        {exam.title}
                                      </span>
                                      <span className="text-[10px] font-medium text-orange-800/70 dark:text-orange-300/70 mt-0.5">
                                        {exam.marks} Marks
                                      </span>
                                    </div>
                                  ))}

                                  {dayPeriods.length === 0 && !hasExams && dayHoliday ? (
                                    /* Clean ERP Holiday Box */
                                    <div className="flex-1 flex flex-col items-center justify-center bg-red-50/50 dark:bg-red-900/10 rounded-md border border-red-100 dark:border-red-900/20 mx-0.5 mb-0.5 p-2 text-center">
                                      <span className="text-xs font-bold text-red-500/90 dark:text-red-400/90 uppercase tracking-wide mb-0.5">
                                        Holiday
                                      </span>
                                      <span className="text-[10px] font-medium text-red-600/70 dark:text-red-300/70 line-clamp-2 leading-tight">
                                        {dayHoliday.title}
                                      </span>
                                    </div>
                                  ) : dayPeriods.length === 0 && !hasExams && isWeekend ? (
                                    /* Clean ERP Weekend Box */
                                    <div className="flex-1 flex items-center justify-center">
                                      <span className="text-xs font-medium text-muted-foreground/40">
                                        Weekend
                                      </span>
                                    </div>
                                  ) : dayPeriods.length === 0 && !hasExams && !dayHoliday && !isWeekend ? (
                                    /* Blank working day with no classes for this subject */
                                    <div className="flex-1 flex items-center justify-center">
                                      <span className="text-[10px] font-medium text-muted-foreground/30">
                                        No Classes
                                      </span>
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Micro Plan Modal */}
        {selectedPeriod && selectedPeriod.plan_json && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setSelectedPeriod(null)}></div>
            <div className="relative bg-white dark:bg-zinc-950 w-full max-w-4xl max-h-full rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-black/10 dark:border-white/10">
              {/* Modal Header */}
              <div className="flex items-center justify-between p-6 border-b border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 uppercase tracking-wider">
                      {selectedPeriod.period_slot}
                    </span>
                    <span className="text-xs font-medium text-muted-foreground">{new Date(selectedPeriod.scheduled_date).toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</span>
                  </div>
                  <h2 className="text-2xl font-bold text-foreground">{selectedPeriod.chapter_name || "Buffer Period"}</h2>
                  {selectedPeriod.primary_concept_name && (
                    <div className="flex items-center gap-1 mt-1 text-sm text-muted-foreground font-medium">
                      <Layers className="h-4 w-4" />
                      {selectedPeriod.primary_concept_name}
                    </div>
                  )}
                </div>
                <button 
                  onClick={() => setSelectedPeriod(null)} 
                  className="p-2 rounded-full bg-black/5 dark:bg-white/10 hover:bg-black/10 dark:hover:bg-white/20 transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Modal Body */}
              <div className="p-6 overflow-y-auto space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="bg-white dark:bg-black/20 rounded-xl p-4 border border-black/10 dark:border-white/10 shadow-sm">
                    <h5 className="text-sm font-bold text-blue-700 dark:text-blue-400 mb-2 flex justify-between items-center">
                      Engage (Hook) <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50">{selectedPeriod.plan_json.engage?.duration_min} min</span>
                    </h5>
                    <p className="text-sm text-foreground/80 leading-relaxed">{selectedPeriod.plan_json.engage?.description}</p>
                  </div>
                  <div className="bg-white dark:bg-black/20 rounded-xl p-4 border border-black/10 dark:border-white/10 shadow-sm">
                    <h5 className="text-sm font-bold text-blue-700 dark:text-blue-400 mb-2 flex justify-between items-center">
                      Explore <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50">{selectedPeriod.plan_json.explore?.duration_min} min</span>
                    </h5>
                    <p className="text-sm text-foreground/80 leading-relaxed">{selectedPeriod.plan_json.explore?.activity_description}</p>
                  </div>
                  <div className="bg-white dark:bg-black/20 rounded-xl p-4 border border-black/10 dark:border-white/10 shadow-sm">
                    <h5 className="text-sm font-bold text-blue-700 dark:text-blue-400 mb-2 flex justify-between items-center">
                      Explain (Core) <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50">{selectedPeriod.plan_json.explain?.duration_min} min</span>
                    </h5>
                    <p className="text-sm text-foreground/80 leading-relaxed">{selectedPeriod.plan_json.explain?.strategy}</p>
                  </div>
                  <div className="bg-white dark:bg-black/20 rounded-xl p-4 border border-black/10 dark:border-white/10 shadow-sm">
                    <h5 className="text-sm font-bold text-blue-700 dark:text-blue-400 mb-2 flex justify-between items-center">
                      Elaborate <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/50">{selectedPeriod.plan_json.elaborate?.duration_min} min</span>
                    </h5>
                    <p className="text-sm text-foreground/80 leading-relaxed">{selectedPeriod.plan_json.elaborate?.real_world_application}</p>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="bg-emerald-500/5 rounded-xl p-4 border border-emerald-500/20">
                    <h5 className="text-sm font-bold text-emerald-700 dark:text-emerald-400 mb-3 flex items-center gap-2">
                      <User className="h-4 w-4" /> Differentiated Learning
                    </h5>
                    <div className="space-y-3">
                      <div className="bg-white/50 dark:bg-black/20 p-3 rounded-lg border border-emerald-500/10">
                        <span className="text-xs font-bold text-emerald-800 dark:text-emerald-300 uppercase tracking-wider block mb-1">Remedial Strategy</span>
                        <p className="text-sm text-foreground/80">{selectedPeriod.plan_json.differentiation?.remedial_strategy}</p>
                      </div>
                      <div className="bg-white/50 dark:bg-black/20 p-3 rounded-lg border border-emerald-500/10">
                        <span className="text-xs font-bold text-emerald-800 dark:text-emerald-300 uppercase tracking-wider block mb-1">Enrichment Activity</span>
                        <p className="text-sm text-foreground/80">{selectedPeriod.plan_json.differentiation?.enrichment_activity}</p>
                      </div>
                    </div>
                  </div>

                  <div className="bg-amber-500/5 rounded-xl p-4 border border-amber-500/20">
                    <h5 className="text-sm font-bold text-amber-700 dark:text-amber-400 mb-3 flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4" /> Formative Assessment
                    </h5>
                    <div className="space-y-3">
                      {selectedPeriod.plan_json.formative_assessment?.map((mcq: any, i: number) => (
                        <div key={i} className="bg-white/50 dark:bg-black/20 p-3 rounded-lg border border-amber-500/10 text-sm">
                          <p className="font-semibold text-foreground mb-1"><span className="text-amber-700 dark:text-amber-500">Q{i+1}.</span> {mcq.question}</p>
                          <div className="pl-5 space-y-1 mt-2">
                            {mcq.options.map((opt: string, j: number) => (
                              <div key={j} className={`flex items-center gap-2 ${opt === mcq.correct_answer ? 'text-emerald-600 dark:text-emerald-400 font-medium' : 'text-muted-foreground'}`}>
                                <div className={`w-1.5 h-1.5 rounded-full ${opt === mcq.correct_answer ? 'bg-emerald-500' : 'bg-black/20 dark:bg-white/20'}`} />
                                <span>{opt}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3 pt-4 border-t border-black/10 dark:border-white/10">
                  {selectedPeriod.blooms_level && (
                    <span className="bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300 px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider">
                      Bloom's Taxonomy: {selectedPeriod.blooms_level}
                    </span>
                  )}
                  {selectedPeriod.pedagogy_method && (
                    <span className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider">
                      Pedagogy: {selectedPeriod.pedagogy_method}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
      {/* --- Modals and existing UI continue --- */}
      {teacherModalData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-md p-4 transition-all duration-500 ease-out">
          <div className="w-full max-w-4xl bg-white/60 dark:bg-black/60 backdrop-blur-[40px] border-[0.5px] border-black/10 dark:border-white/20 rounded-[2rem] shadow-[0_8px_32px_0_rgba(0,0,0,0.2)] saturate-150 overflow-hidden flex flex-col max-h-[90vh]">
             <div className="p-8 border-b-[0.5px] border-black/5 dark:border-white/10 flex items-center justify-between bg-white/20 dark:bg-black/20">
               <h2 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Assign Chapters to Teachers</h2>
               <button onClick={() => setTeacherModalData(null)} className="p-2 rounded-full border-[0.5px] border-black/10 dark:border-white/10 bg-white/30 dark:bg-black/30 backdrop-blur-md hover:bg-white/50 dark:hover:bg-white/10 transition-all">
                 <X className="w-5 h-5 text-slate-700 dark:text-slate-300" />
               </button>
             </div>
             <div className="p-8 overflow-y-auto space-y-8">
               <p className="text-sm font-medium text-slate-600 dark:text-slate-400 bg-white/40 dark:bg-black/40 border-[0.5px] border-black/5 dark:border-white/5 p-4 rounded-2xl backdrop-blur-md">We detected {teacherModalData.teachers.length} teachers for this subject. You can manually assign chapters to specific teachers, or let the AI auto-split them based on their available periods.</p>
               
               <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                 {teacherModalData.teachers.map((t: any) => (
                   <div key={t.id} className="border-[0.5px] border-black/10 dark:border-white/10 rounded-3xl p-6 bg-white/40 dark:bg-black/40 backdrop-blur-md shadow-[0_4px_16px_0_rgba(0,0,0,0.05)] flex flex-col">
                     <h3 className="font-bold text-xl text-slate-800 dark:text-slate-100 mb-6 flex items-center">
                       <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-900/50 border-[0.5px] border-blue-200 dark:border-blue-800 flex items-center justify-center mr-3 shadow-sm">
                         <User className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                       </div>
                       {t.name}
                     </h3>
                     <div className="space-y-3 flex-1 overflow-y-auto pr-2 custom-scrollbar">
                       {teacherModalData.chapters.map((ch: any) => {
                         const isAssignedToMe = teacherAssignments[t.id]?.includes(ch.chapter_id);
                         const isAssignedToOther = Object.keys(teacherAssignments).some(otherTid => otherTid != t.id && teacherAssignments[otherTid].includes(ch.chapter_id));
                         
                         return (
                           <label key={ch.chapter_id} className={`flex items-start space-x-4 p-4 rounded-2xl border-[0.5px] cursor-pointer transition-all duration-300 ${isAssignedToMe ? 'border-blue-400 bg-white/80 dark:bg-blue-900/40 shadow-md shadow-blue-500/10' : isAssignedToOther ? 'border-black/5 dark:border-white/5 opacity-40 grayscale cursor-not-allowed bg-white/20 dark:bg-black/20' : 'border-black/10 dark:border-white/10 hover:border-blue-300 dark:hover:border-blue-700 bg-white/50 dark:bg-black/50 hover:bg-white/80 dark:hover:bg-white/5 hover:shadow-sm'}`}>
                             <div className="pt-0.5 flex-shrink-0">
                               <input 
                                 type="checkbox" 
                                 className="w-5 h-5 rounded-md border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-700 dark:ring-offset-slate-900"
                                 checked={isAssignedToMe}
                                 disabled={isAssignedToOther}
                                 onChange={(e) => {
                                   setTeacherAssignments((prev: any) => {
                                     const next = { ...prev };
                                     if (e.target.checked) {
                                       next[t.id] = [...(next[t.id] || []), ch.chapter_id];
                                     } else {
                                       next[t.id] = (next[t.id] || []).filter((id: number) => id !== ch.chapter_id);
                                     }
                                     return next;
                                   });
                                 }}
                               />
                             </div>
                             <div className="flex-1 min-w-0">
                               <p className={`text-sm font-semibold line-clamp-2 leading-relaxed ${isAssignedToMe ? 'text-blue-900 dark:text-blue-100' : 'text-slate-800 dark:text-slate-200'}`}>{ch.chapter_name}</p>
                               <div className="flex items-center mt-2 space-x-2">
                                 <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-black/5 dark:bg-white/10 text-slate-600 dark:text-slate-300 border-[0.5px] border-black/5 dark:border-white/5 backdrop-blur-sm">
                                   <Clock className="w-3 h-3 mr-1" />
                                   {ch.allocated_periods} periods
                                 </span>
                               </div>
                             </div>
                           </label>
                         )
                       })}
                     </div>
                   </div>
                 ))}
               </div>
             </div>
             <div className="p-6 md:p-8 border-t-[0.5px] border-black/5 dark:border-white/10 flex flex-col md:flex-row justify-between items-center gap-4 bg-white/30 dark:bg-black/30 backdrop-blur-lg">
               <button onClick={() => executeMesoPlan(null)} disabled={loading} className="w-full md:w-auto px-6 py-3 flex items-center justify-center text-sm font-semibold rounded-2xl border-[0.5px] border-black/10 dark:border-white/20 bg-white/50 dark:bg-black/50 backdrop-blur-md shadow-sm hover:bg-white/80 dark:hover:bg-white/10 transition-all disabled:opacity-50 text-slate-700 dark:text-slate-200 group">
                 <div className="bg-purple-100 dark:bg-purple-900/50 border-[0.5px] border-purple-200 dark:border-purple-800 p-1.5 rounded-full mr-3 group-hover:scale-110 transition-transform">
                   <Wand2 className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
                 </div>
                 Auto-Split (AI Generated)
               </button>
               <div className="flex w-full md:w-auto space-x-4">
                 <button onClick={() => setTeacherModalData(null)} className="flex-1 md:flex-none px-6 py-3 text-sm font-semibold text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-all bg-transparent hover:bg-black/5 dark:hover:bg-white/5 rounded-2xl">
                   Cancel
                 </button>
                 <button onClick={() => executeMesoPlan(teacherAssignments)} className="flex-1 md:flex-none px-8 py-3 text-sm font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-2xl shadow-[0_8px_16px_rgba(37,99,235,0.2)] hover:shadow-[0_8px_24px_rgba(37,99,235,0.3)] transition-all active:scale-[0.98]">
                   Save & Generate
                 </button>
               </div>
             </div>
          </div>
        </div>
      )}
    </div>
  );
}
