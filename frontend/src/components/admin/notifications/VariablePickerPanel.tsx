"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Sparkles } from "lucide-react";

interface Variable {
  variable: string;
  label: string;
  description: string;
}

interface VariablePickerPanelProps {
  variables: Variable[];
  onInsert: (variable: string, target: "title_template" | "message_template") => void;
}

export default function VariablePickerPanel({ variables, onInsert }: VariablePickerPanelProps) {
  if (variables.length === 0) return null;

  return (
    <Card className="bg-info-50 border-info-200">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-info-600" />
          Biến tự động
        </CardTitle>
        <CardDescription className="text-xs">
          Nhấp vào biến phía dưới để chèn vào nội dung. Biến sẽ tự động thay thế khi gửi thông báo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {variables.map((v) => (
            <TooltipProvider key={v.variable} delayDuration={0}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-xs h-7"
                    onClick={() => {
                      const activeElement = document.activeElement;
                      if (activeElement?.id === "title_template") {
                        onInsert(v.variable, "title_template");
                      } else {
                        onInsert(v.variable, "message_template");
                      }
                    }}
                  >
                    {v.label}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">
                    <code className="font-mono">{v.variable}</code> - {v.description}
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
