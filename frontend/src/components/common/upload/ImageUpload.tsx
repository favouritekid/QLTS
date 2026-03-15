// src/components/common/upload/ImageUpload.tsx
"use client";

import * as React from "react";
import { Camera, X, Loader2, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface ImageUploadProps {
  /** Current image URL or data URL */
  value?: string | null;
  /** Callback when image changes */
  onChange: (file: File | null, previewUrl: string | null) => void;
  /** Callback when image is uploaded (return URL) */
  onUpload?: (file: File) => Promise<string>;
  /** Field label */
  label?: string;
  /** Helper text */
  description?: string;
  /** Error message */
  error?: string;
  /** Mark field as required */
  required?: boolean;
  /** Avatar size */
  size?: "sm" | "md" | "lg" | "xl";
  /** Shape */
  shape?: "circle" | "square";
  /** Accepted image types */
  accept?: string;
  /** Maximum file size in bytes */
  maxSize?: number;
  /** Compress image before upload */
  compress?: boolean;
  /** Compression quality (0-1) */
  compressionQuality?: number;
  /** Maximum image dimension (width or height) */
  maxDimension?: number;
  /** Disable the upload */
  disabled?: boolean;
  /** Container class name */
  containerClassName?: string;
  /** Placeholder text/initial */
  placeholder?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_MAX_SIZE = 2 * 1024 * 1024; // 2MB
const DEFAULT_ACCEPT = "image/png,image/jpeg,image/jpg,image/webp";
const DEFAULT_COMPRESSION_QUALITY = 0.8;
const DEFAULT_MAX_DIMENSION = 1024;

const SIZE_CLASSES = {
  sm: "h-16 w-16",
  md: "h-24 w-24",
  lg: "h-32 w-32",
  xl: "h-40 w-40",
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Compress image using canvas
 */
async function compressImage(
  file: File,
  maxDimension: number,
  quality: number
): Promise<File> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    img.onload = () => {
      let { width, height } = img;

      // Calculate new dimensions
      if (width > maxDimension || height > maxDimension) {
        if (width > height) {
          height = (height / width) * maxDimension;
          width = maxDimension;
        } else {
          width = (width / height) * maxDimension;
          height = maxDimension;
        }
      }

      canvas.width = width;
      canvas.height = height;

      ctx?.drawImage(img, 0, 0, width, height);

      canvas.toBlob(
        (blob) => {
          if (blob) {
            const compressedFile = new File([blob], file.name, {
              type: "image/jpeg",
              lastModified: Date.now(),
            });
            resolve(compressedFile);
          } else {
            reject(new Error("Failed to compress image"));
          }
        },
        "image/jpeg",
        quality
      );
    };

    img.onerror = () => reject(new Error("Failed to load image"));
    img.src = URL.createObjectURL(file);
  });
}

/**
 * Read file as data URL
 */
function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function ImageUpload({
  value,
  onChange,
  onUpload,
  label,
  description,
  error,
  required,
  size = "lg",
  shape = "circle",
  accept = DEFAULT_ACCEPT,
  maxSize = DEFAULT_MAX_SIZE,
  compress = true,
  compressionQuality = DEFAULT_COMPRESSION_QUALITY,
  maxDimension = DEFAULT_MAX_DIMENSION,
  disabled = false,
  containerClassName,
  placeholder,
}: ImageUploadProps) {
  const [isLoading, setIsLoading] = React.useState(false);
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(value || null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Sync preview with value
  React.useEffect(() => {
    setPreviewUrl(value || null);
  }, [value]);

  const hasError = !!error;

  // Validate file
  const validateFile = React.useCallback(
    (file: File): string | null => {
      // Extension validation (primary defense - harder to spoof than MIME)
      const ext = file.name.split('.').pop()?.toLowerCase();
      const allowedExtensions = ['png', 'jpg', 'jpeg', 'webp'];
      if (!ext || !allowedExtensions.includes(ext)) {
        return "Chỉ chấp nhận file PNG, JPG hoặc WebP";
      }

      // Block SVG (XSS vector via embedded scripts)
      if (ext === 'svg' || file.type === 'image/svg+xml') {
        return "File SVG không được phép vì lý do bảo mật";
      }

      if (file.size > maxSize) {
        return `Ảnh quá lớn. Kích thước tối đa: ${Math.round(maxSize / 1024 / 1024)}MB`;
      }

      // MIME check (secondary defense)
      const acceptedTypes = accept.split(",").map((t) => t.trim());
      if (!acceptedTypes.includes(file.type)) {
        return "Chỉ chấp nhận file PNG, JPG hoặc WebP";
      }
      return null;
    },
    [maxSize, accept]
  );

  // Handle file selection
  const handleFileChange = React.useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || disabled) return;

      // Validate
      const validationError = validateFile(file);
      if (validationError) {
        onChange(null, null);
        return;
      }

      setIsLoading(true);

      try {
        // Compress if enabled
        let processedFile = file;
        if (compress && file.type.startsWith("image/")) {
          processedFile = await compressImage(file, maxDimension, compressionQuality);
        }

        // Generate preview
        const dataUrl = await readFileAsDataURL(processedFile);
        setPreviewUrl(dataUrl);

        // Upload if handler provided
        if (onUpload) {
          const url = await onUpload(processedFile);
          onChange(processedFile, url);
        } else {
          onChange(processedFile, dataUrl);
        }
      } catch (err) {
        console.error("Image upload error:", err);
        onChange(null, null);
      } finally {
        setIsLoading(false);
      }

      // Reset input
      e.target.value = "";
    },
    [onChange, onUpload, validateFile, compress, maxDimension, compressionQuality, disabled]
  );

  // Handle remove
  const handleRemove = React.useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setPreviewUrl(null);
      onChange(null, null);
    },
    [onChange]
  );

  // Handle click
  const handleClick = React.useCallback(() => {
    if (!disabled && !isLoading) {
      inputRef.current?.click();
    }
  }, [disabled, isLoading]);

  return (
    <div className={cn("space-y-2", containerClassName)}>
      {/* Label */}
      {label && (
        <Label className={cn(hasError && "text-destructive")}>
          {label}
          {required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}

      {/* Image preview */}
      <div className="relative inline-block">
        <Avatar
          className={cn(
            SIZE_CLASSES[size],
            shape === "square" && "rounded-lg",
            "cursor-pointer border-2 border-dashed transition-colors",
            hasError ? "border-destructive" : "border-muted-foreground/25 hover:border-primary",
            disabled && "opacity-50 cursor-not-allowed"
          )}
          onClick={handleClick}
        >
          <AvatarImage src={previewUrl || undefined} alt="Preview" />
          <AvatarFallback
            className={cn(
              shape === "square" && "rounded-lg",
              "bg-muted"
            )}
          >
            {isLoading ? (
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            ) : placeholder ? (
              <span className="text-lg font-medium text-muted-foreground">
                {placeholder}
              </span>
            ) : (
              <User className="h-8 w-8 text-muted-foreground" />
            )}
          </AvatarFallback>
        </Avatar>

        {/* Camera button */}
        <Button
          type="button"
          variant="secondary"
          size="icon"
          className={cn(
            "absolute -bottom-1 -right-1 h-8 w-8 rounded-full shadow-md",
            disabled && "opacity-50 cursor-not-allowed"
          )}
          onClick={handleClick}
          disabled={disabled || isLoading}
          aria-label="Chọn ảnh"
        >
          <Camera className="h-4 w-4" />
        </Button>

        {/* Remove button */}
        {previewUrl && !disabled && (
          <Button
            type="button"
            variant="destructive"
            size="icon"
            className="absolute -top-1 -right-1 h-6 w-6 rounded-full shadow-md"
            onClick={handleRemove}
            disabled={isLoading}
            aria-label="Xóa ảnh"
          >
            <X className="h-3 w-3" />
          </Button>
        )}

        {/* Hidden input */}
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={accept}
          onChange={handleFileChange}
          disabled={disabled}
        />
      </div>

      {/* Description */}
      {description && !error && (
        <p className="text-sm text-muted-foreground">{description}</p>
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

export default ImageUpload;
