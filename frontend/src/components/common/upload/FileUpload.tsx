// src/components/common/upload/FileUpload.tsx
"use client";

import * as React from "react";
import { Upload, X, File, Loader2, AlertCircle, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface FileItem {
  id: string;
  file: File;
  progress: number;
  status: "pending" | "uploading" | "success" | "error";
  error?: string;
  url?: string;
}

export interface FileUploadProps {
  /** Current files */
  value?: FileItem[];
  /** Callback when files change */
  onChange?: (files: FileItem[]) => void;
  /** Callback when a file is uploaded (return URL) */
  onUpload?: (file: File) => Promise<string>;
  /** Field label */
  label?: string;
  /** Helper text */
  description?: string;
  /** Error message */
  error?: string;
  /** Mark field as required */
  required?: boolean;
  /** Allow multiple files */
  multiple?: boolean;
  /** Maximum file size in bytes */
  maxSize?: number;
  /** Maximum number of files */
  maxFiles?: number;
  /** Accepted file types (e.g., "image/*", ".pdf") */
  accept?: string;
  /** Disable the upload */
  disabled?: boolean;
  /** Container class name */
  containerClassName?: string;
  /** Drop zone class name */
  dropZoneClassName?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_MAX_SIZE = 10 * 1024 * 1024; // 10MB
const DEFAULT_MAX_FILES = 10;

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function generateId(): string {
  return `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function FileUpload({
  value = [],
  onChange,
  onUpload,
  label,
  description,
  error,
  required,
  multiple = false,
  maxSize = DEFAULT_MAX_SIZE,
  maxFiles = DEFAULT_MAX_FILES,
  accept,
  disabled = false,
  containerClassName,
  dropZoneClassName,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const hasError = !!error;
  const canAddMore = multiple ? value.length < maxFiles : value.length === 0;

  // Validate file
  const validateFile = React.useCallback(
    (file: File): string | null => {
      if (file.size > maxSize) {
        return `File qua lon. Kich thuoc toi da: ${formatFileSize(maxSize)}`;
      }
      if (accept) {
        const acceptedTypes = accept.split(",").map((t) => t.trim());
        const fileType = file.type;
        const fileExtension = `.${file.name.split(".").pop()?.toLowerCase()}`;

        const isAccepted = acceptedTypes.some((type) => {
          if (type.startsWith(".")) {
            return fileExtension === type.toLowerCase();
          }
          if (type.endsWith("/*")) {
            return fileType.startsWith(type.slice(0, -1));
          }
          return fileType === type;
        });

        if (!isAccepted) {
          return "Loai file khong duoc ho tro";
        }
      }
      return null;
    },
    [maxSize, accept]
  );

  // Handle file selection
  const handleFiles = React.useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0 || disabled) return;

      const newFiles: FileItem[] = [];
      const fileArray = Array.from(files);

      // Limit number of files
      const filesToProcess = multiple
        ? fileArray.slice(0, maxFiles - value.length)
        : [fileArray[0]];

      for (const file of filesToProcess) {
        const validationError = validateFile(file);
        newFiles.push({
          id: generateId(),
          file,
          progress: 0,
          status: validationError ? "error" : "pending",
          error: validationError || undefined,
        });
      }

      const updatedFiles = multiple ? [...value, ...newFiles] : newFiles;
      onChange?.(updatedFiles);

      // Auto-upload valid files
      if (onUpload) {
        for (const fileItem of newFiles) {
          if (fileItem.status === "pending") {
            uploadFile(fileItem, updatedFiles);
          }
        }
      }
    },
    [value, onChange, onUpload, multiple, maxFiles, validateFile, disabled]
  );

  // Upload a single file
  const uploadFile = React.useCallback(
    async (fileItem: FileItem, currentFiles: FileItem[]) => {
      if (!onUpload) return;

      // Update status to uploading
      const updateFile = (updates: Partial<FileItem>) => {
        onChange?.(
          currentFiles.map((f) =>
            f.id === fileItem.id ? { ...f, ...updates } : f
          )
        );
      };

      updateFile({ status: "uploading", progress: 10 });

      try {
        // Simulate progress (since we don't have real progress events)
        const progressInterval = setInterval(() => {
          updateFile({ progress: Math.min(90, fileItem.progress + 10) });
        }, 200);

        const url = await onUpload(fileItem.file);

        clearInterval(progressInterval);
        updateFile({ status: "success", progress: 100, url });
      } catch (err) {
        updateFile({
          status: "error",
          progress: 0,
          error: err instanceof Error ? err.message : "Upload that bai",
        });
      }
    },
    [onUpload, onChange]
  );

  // Handle remove file
  const handleRemove = React.useCallback(
    (id: string) => {
      onChange?.(value.filter((f) => f.id !== id));
    },
    [value, onChange]
  );

  // Drag & drop handlers
  const handleDragOver = React.useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = React.useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = React.useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  // Click to select
  const handleClick = React.useCallback(() => {
    if (!disabled && canAddMore) {
      inputRef.current?.click();
    }
  }, [disabled, canAddMore]);

  return (
    <div className={cn("space-y-2", containerClassName)}>
      {/* Label */}
      {label && (
        <Label className={cn(hasError && "text-destructive")}>
          {label}
          {required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}

      {/* Drop zone */}
      {canAddMore && (
        <div
          onClick={handleClick}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            "border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors",
            isDragging && "border-primary bg-primary/5",
            disabled && "opacity-50 cursor-not-allowed",
            hasError && "border-destructive",
            !isDragging && !hasError && "border-muted-foreground/25 hover:border-primary",
            dropZoneClassName
          )}
        >
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            multiple={multiple}
            accept={accept}
            onChange={(e) => handleFiles(e.target.files)}
            disabled={disabled}
          />
          <Upload className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
          <p className="text-sm text-muted-foreground">
            Keo tha file vao day hoac <span className="text-primary font-medium">chon file</span>
          </p>
          {description && (
            <p className="text-xs text-muted-foreground mt-1">{description}</p>
          )}
        </div>
      )}

      {/* File list */}
      {value.length > 0 && (
        <div className="space-y-2">
          {value.map((fileItem) => (
            <div
              key={fileItem.id}
              className={cn(
                "flex items-center gap-3 p-3 rounded-lg border",
                fileItem.status === "error" && "border-destructive bg-destructive/5"
              )}
            >
              {/* Icon */}
              <div className="shrink-0">
                {fileItem.status === "uploading" && (
                  <Loader2 className="h-5 w-5 animate-spin text-primary" />
                )}
                {fileItem.status === "success" && (
                  <CheckCircle className="h-5 w-5 text-green-500" />
                )}
                {fileItem.status === "error" && (
                  <AlertCircle className="h-5 w-5 text-destructive" />
                )}
                {fileItem.status === "pending" && (
                  <File className="h-5 w-5 text-muted-foreground" />
                )}
              </div>

              {/* File info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{fileItem.file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatFileSize(fileItem.file.size)}
                </p>
                {fileItem.status === "error" && fileItem.error && (
                  <p className="text-xs text-destructive">{fileItem.error}</p>
                )}
                {fileItem.status === "uploading" && (
                  <Progress value={fileItem.progress} className="h-1 mt-1" />
                )}
              </div>

              {/* Remove button */}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 h-8 w-8"
                onClick={() => handleRemove(fileItem.id)}
                disabled={fileItem.status === "uploading"}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Error message */}
      {error && (
        <p className="text-sm font-medium text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default FileUpload;
