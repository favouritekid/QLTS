'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { AlertTriangle } from 'lucide-react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-[50vh] w-full flex-col items-center justify-center gap-4">
      <div className="flex flex-col items-center gap-2 text-center">
        <AlertTriangle className="h-10 w-10 text-destructive" />
        <h2 className="text-xl font-semibold">Đã xảy ra lỗi!</h2>
        <p className="text-muted-foreground">
          Không thể tải thông tin hồ sơ tuyển sinh.
        </p>
      </div>
      <div className="flex gap-2">
        <Button onClick={() => window.location.reload()} variant="outline">
          Tải lại trang
        </Button>
        <Button onClick={() => reset()}>Thử lại</Button>
      </div>
    </div>
  );
}
