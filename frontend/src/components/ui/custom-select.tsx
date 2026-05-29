import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check } from "lucide-react";

interface Option {
  label: string;
  value: string;
}

interface CustomSelectProps {
  value: string;
  onChange: (val: string) => void;
  options: Option[];
  placeholder?: string;
}

export function CustomSelect({ value, onChange, options, placeholder }: CustomSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedLabel = options.find((o) => o.value === value)?.label || placeholder;

  useEffect(() => {
    function handleOutsideClick(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  return (
    <div className="relative w-full" ref={containerRef}>
      <div
        onClick={() => setIsOpen(!isOpen)}
        className="flex h-10 w-full items-center justify-between rounded-xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/50 dark:bg-black/50 px-3 text-sm outline-none backdrop-blur-md transition-colors focus:border-primary focus:ring-1 focus:ring-primary cursor-pointer hover:bg-white/60 dark:hover:bg-black/60"
      >
        <span className={!value ? "text-muted-foreground/50" : "text-foreground"}>
          {selectedLabel}
        </span>
        <ChevronDown className={`h-4 w-4 text-muted-foreground/50 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`} />
      </div>
      
      {isOpen && (
        <div className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-xl border-[0.5px] border-black/10 dark:border-white/10 bg-white/95 dark:bg-black/95 p-1.5 text-base shadow-xl backdrop-blur-md animate-in fade-in zoom-in-95 duration-100 ease-out custom-scrollbar">
          {options.map((option) => (
            <div
              key={option.value}
              onClick={() => {
                onChange(option.value);
                setIsOpen(false);
              }}
              className={`relative flex w-full cursor-pointer select-none items-center rounded-[8px] py-2 pl-8 pr-2 text-sm outline-none transition-colors hover:bg-black/5 dark:hover:bg-white/10 ${
                value === option.value ? "bg-black/5 dark:bg-white/10 font-semibold text-foreground" : "text-foreground/90 font-medium"
              }`}
            >
              {value === option.value && (
                <span className="absolute left-2.5 flex items-center justify-center">
                  <Check className="h-4 w-4 text-foreground" />
                </span>
              )}
              {option.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
