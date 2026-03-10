// src/hooks/useAuth.ts
import { useAuthStore } from "@/lib/stores/auth.store";
import { api, setApiLoggedOut } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type {
  LoginRequest,
  LoginResponse,
  User,
  ApiErrorResponse,
  MeResponse,
  UserCreate,
  ForgotPasswordSchema,
  ResetPasswordSchema,
  ChangePasswordSchema,
  UserUpdateProfile,
} from "@/types/api.types";
import React, { useEffect } from "react";
import { AxiosError } from "axios";
import { triggerBannerCheck } from "@/components/layouts/SecurityBanner";

/**
 * ✅ PHASE 1 - WEEK 3 - DAY 2: Added initialData support for SSR
 */
export interface UseAuthOptions {
  initialData?: User;
}

function isValidRedirect(url: string | null): url is string {
  if (!url) return false;
  if (!url.startsWith('/')) return false;
  if (url.startsWith('//')) return false;
  if (url.includes(':')) return false;
  return true;
}

export function useAuth(options?: UseAuthOptions) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // ✅ PERF FIX: Granular selectors to avoid re-rendering on unrelated store changes
  const userFromStore = useAuthStore(s => s.user);
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  const setAuth = useAuthStore(s => s.setAuth);
  const logoutStore = useAuthStore(s => s.logout);

  // MFA callback ref - set by LoginForm to intercept MFA responses
  const mfaCallbackRef = React.useRef<{
    onSuccess?: (response: LoginResponse) => void;
  }>({});

  const loginMutation = useMutation<
    LoginResponse,
    AxiosError<ApiErrorResponse>,
    LoginRequest
  >({
    mutationFn: async (credentials: LoginRequest) => {
      const params = new URLSearchParams();
      params.append("username", credentials.username);
      params.append("password", credentials.password);

      const loginRes = await api.post<LoginResponse>(API_ENDPOINTS.AUTH.LOGIN, params.toString(), {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        withCredentials: true,
      });

      return loginRes.data;
    },
    onSuccess: async (loginResponse: LoginResponse) => {
      // MFA REQUIRED: Don't complete login, let LoginForm handle MFA step
      if (loginResponse.mfa_required && loginResponse.mfa_token) {
        mfaCallbackRef.current.onSuccess?.(loginResponse);
        return; // Stop here - don't setAuth or redirect
      }

      // Clear stale cache from previous session before setting new auth.
      // This prevents data leakage between different user accounts and
      // avoids clearing during logout (which causes 401 race conditions).
      queryClient.clear();
      setApiLoggedOut(false); // Re-enable API requests

      const { user, login_notification } = loginResponse;

      setAuth(user);
      triggerBannerCheck(user.password_reset_required);
      toast.success("Đăng nhập thành công!");

      if (login_notification) {
        const locationInfo = login_notification.location || "Không rõ vị trí";
        const deviceInfo = login_notification.device || "Không rõ thiết bị";

        toast.warning(
          `Phát hiện đăng nhập đáng ngờ\nIP: ${login_notification.ip_address} - ${locationInfo}\n${deviceInfo}`,
          {
            duration: 15000,
            id: `suspicious-login-${login_notification.login_id}`,
            action: {
              label: "Xem chi tiết",
              onClick: async () => {
                if (login_notification.notification_id) {
                  try {
                    await api.post(API_ENDPOINTS.NOTIFICATIONS.MARK_AS_READ, {
                      notification_ids: [login_notification.notification_id],
                    });
                    queryClient.invalidateQueries({ queryKey: ["notifications"] });
                  } catch (err) {
                    console.error("[useAuth] Failed to mark notification as read:", err);
                  }
                }
                router.push("/settings/login-history");
              },
            },
          }
        );
      }

      const redirect = new URLSearchParams(window.location.search).get("redirect");
      const defaultPath = user.role === "officer"
        ? "/dashboard/officer"
        : user.role === "collaborator"
          ? "/ctv"
          : "/dashboard";
      router.push(isValidRedirect(redirect) ? redirect : defaultPath);
    },
    // No toast here - LoginForm shows inline error via loginError
  });

  // MFA verification mutation
  const verifyMfaMutation = useMutation<
    LoginResponse,
    AxiosError<ApiErrorResponse>,
    { mfa_token: string; code: string }
  >({
    mutationFn: async (data) => {
      const res = await api.post<LoginResponse>(API_ENDPOINTS.AUTH.VERIFY_MFA, data, {
        withCredentials: true,
      });
      return res.data;
    },
    onSuccess: async (loginResponse: LoginResponse) => {
      // Clear stale cache from previous session (same as loginMutation).
      queryClient.clear();
      setApiLoggedOut(false); // Re-enable API requests

      const { user, login_notification } = loginResponse;

      setAuth(user);
      triggerBannerCheck(user.password_reset_required);
      toast.success("Đăng nhập thành công!");

      if (login_notification) {
        toast.warning(
          `Phát hiện đăng nhập đáng ngờ\nIP: ${login_notification.ip_address}`,
          { duration: 15000 }
        );
      }

      const redirect = new URLSearchParams(window.location.search).get("redirect");
      const defaultPath = user.role === "officer"
        ? "/dashboard/officer"
        : user.role === "collaborator"
          ? "/ctv"
          : "/dashboard";
      router.push(isValidRedirect(redirect) ? redirect : defaultPath);
    },
    // No toast here - LoginForm shows inline error via verifyMfaError
  });

  const logoutMutation = useMutation<void, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      // ========================================
      // OPTIMISTIC LOGOUT
      // ========================================
      // 1. Block API requests (prevents 401 cascade after cookies cleared)
      // 2. Clear auth state
      // 3. Redirect to login
      // 4. Call logout API (cookies still present, server clears them)
      //
      // Cache is cleared on next LOGIN to avoid data leakage between users.

      // 🚫 STEP 1: Block all non-auth API requests immediately
      setApiLoggedOut(true);

      // 🧹 STEP 2: Clear client state (isAuthenticated=false)
      logoutStore();

      // 📡 STEP 3: Call logout API (cookies still present, server clears them)
      try {
        await api.post(API_ENDPOINTS.AUTH.LOGOUT, {}, { withCredentials: true });
      } catch {
        // Ignore - user will be redirected regardless
      }

      // 🚀 STEP 4: Hard redirect - more reliable than router.replace()
      // which can fail if the component unmounts during React re-render.
      // Also clears all JS state (module vars, React state) for a clean login page.
      window.location.href = "/login";
    },
    onSuccess: () => {
      // User won't see this toast because they're already on login page
      // But it's good for debugging in console
      console.log("[Logout] Successfully logged out");
    },
    onError: (error) => {
      // This should rarely happen since we handle errors in mutationFn
      console.error("[Logout] Mutation error:", error);
    },
    // NOTE: Do NOT clear queryClient here (neither onSuccess nor onSettled).
    // Even in onSettled, dashboard components may still be mounted (~100ms
    // after router.replace). Clearing cache causes observers to refetch
    // after cookies are already gone → spurious 401 errors.
    // Cache is cleared on next LOGIN instead (see loginMutation/verifyMfaMutation).
  });

  const {
    data: currentUser,
    isLoading: isUserLoading,
    isFetching: isUserFetching,
    error: userError,
    isError: isUserError,
  } = useQuery<
    User, // <<< SỬA LỖI 2: Dùng User từ api.types
    AxiosError<ApiErrorResponse>
  >({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      // ✅ SECURITY FIX: Token is in httpOnly cookie, no need to check localStorage
      const { data } = await api.get<MeResponse>(API_ENDPOINTS.USERS.ME);
      // React Query v5 requires queryFn to never return undefined
      if (data === undefined) throw new Error("No user data returned");
      return data;
    },
    enabled: isAuthenticated, // Only check if user is marked as authenticated
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 3 - DAY 2: SSR support
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: true,
    refetchOnMount: true,
  });

  const registerMutation = useMutation<
    User, // Backend /register trả về User object
    AxiosError<ApiErrorResponse>,
    UserCreate & { confirm_password: string } // Input bao gồm cả confirm password cho validation
  >({
    mutationFn: async (userData) => {
      // Chỉ gửi các trường mà backend yêu cầu (không gửi confirm_password)
      const apiData: UserCreate = {
        username: userData.username,
        email: userData.email,
        password: userData.password,
        full_name: userData.full_name,
      };
      const response = await api.post<User>(API_ENDPOINTS.AUTH.REGISTER, apiData);
      return response.data; // Trả về user đã tạo
    },
    onSuccess: (newUser) => {
      toast.success(`Đăng ký thành công cho ${newUser.username}! Vui lòng đăng nhập.`);
      // Chuyển hướng người dùng đến trang login sau khi đăng ký thành công
      router.push("/login");
    },
    onError: (error) => {
      // Hiển thị lỗi từ backend (ví dụ: username/email đã tồn tại)
      const errorDetail = error.response?.data?.detail;
      let errorMessage = "Đăng ký thất bại.";

      if (typeof errorDetail === "string") {
        errorMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        // Xử lý lỗi validation nếu backend trả về mảng
        errorMessage = errorDetail.map((e) => e.msg || "Lỗi xác thực").join(", ");
      } else if (error.response?.data?.message) {
        errorMessage = error.response.data.message;
      }

      toast.error(errorMessage);
    },
  });

  const forgotPasswordMutation = useMutation<
    { msg: string }, // Kiểu response thành công từ backend
    AxiosError<ApiErrorResponse>,
    ForgotPasswordSchema
  >({
    mutationFn: async (data: ForgotPasswordSchema) => {
      const response = await api.post<{ msg: string }>(API_ENDPOINTS.AUTH.FORGOT_PASSWORD, data);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(data.msg || "Email đặt lại mật khẩu đã được gửi (nếu tài khoản tồn tại).");
      // Có thể thêm thông báo hướng dẫn người dùng kiểm tra email
    },
    onError: (error) => {
      let displayMessage = "Không thể gửi email đặt lại mật khẩu.";
      const errorDetail = error.response?.data?.detail;
      const errorMessageFromData = error.response?.data?.message;

      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (
        Array.isArray(errorDetail) &&
        errorDetail.length > 0 &&
        typeof errorDetail[0].msg === "string"
      ) {
        // Xử lý mảng lỗi validation
        displayMessage = errorDetail[0].msg;
      } else if (typeof errorMessageFromData === "string") {
        displayMessage = errorMessageFromData;
      } else if (typeof error.message === "string") {
        displayMessage = error.message;
      }

      toast.error(displayMessage);
    },
  });

  const resetPasswordMutation = useMutation<
    User, // Backend /reset-password trả về User object
    AxiosError<ApiErrorResponse>,
    ResetPasswordSchema & { confirm_new_password: string } // Input bao gồm cả confirm password
  >({
    mutationFn: async (data) => {
      // Chỉ gửi token và new_password cho API
      const apiData: ResetPasswordSchema = { token: data.token, new_password: data.new_password };
      const response = await api.post<User>(API_ENDPOINTS.AUTH.RESET_PASSWORD, apiData);
      return response.data;
    },
    onSuccess: (user) => {
      toast.success(`Đặt lại mật khẩu cho ${user.username} thành công! Vui lòng đăng nhập.`);
      router.push("/login"); // Chuyển về trang login sau khi reset thành công
    },
    onError: (error) => {
      let displayMessage = "Không thể đặt lại mật khẩu.";
      const errorDetail = error.response?.data?.detail;

      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (
        Array.isArray(errorDetail) &&
        errorDetail.length > 0 &&
        typeof errorDetail[0].msg === "string"
      ) {
        // Xử lý mảng lỗi validation
        displayMessage = errorDetail[0].msg;
      } else if (error.response?.data?.message) {
        displayMessage = error.response.data.message;
      } else if (error.response?.status === 401) {
        displayMessage = "Token đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.";
      }

      toast.error(displayMessage);
    },
  });

  const changePasswordMutation = useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    ChangePasswordSchema & { confirm_new_password: string } // Input bao gồm cả confirm password cho validation
  >({
    mutationFn: async (data) => {
      // Chỉ gửi các trường mà backend yêu cầu (không gửi confirm_new_password)
      const apiData: ChangePasswordSchema = {
        old_password: data.old_password,
        new_password: data.new_password,
      };
      await api.post(API_ENDPOINTS.AUTH.CHANGE_PASSWORD, apiData);
    },
    // 3. Xử lý thành công
    onSuccess: async () => {
      toast.success("Đổi mật khẩu thành công! Đang đăng xuất…");
      setApiLoggedOut(true); // Block API requests trước khi clear
      // 4b. Dọn dẹp state client (Zustand)
      logoutStore();
      // 4c. Dọn dẹp cache (React Query)
      queryClient.clear();
      // 4d. Chuyển hướng
      router.push("/login");
    },
    onError: (error) => {
      // 5. Xử lý lỗi (giữ nguyên)
      let displayMessage = "Không thể đổi mật khẩu.";
      const errorDetail = error.response?.data?.detail;
      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (Array.isArray(errorDetail) && errorDetail.length > 0) {
        displayMessage = errorDetail[0].msg;
      } else if (error.response?.data?.message) {
        displayMessage = error.response.data.message;
      }
      toast.error(displayMessage);
    },
    onSettled: () => {
      // 6. Xóa logic gọi logoutMutation khỏi onSettled
      // KHÔNG CÒN GÌ Ở ĐÂY
    },
  });

  const updateProfileMutation = useMutation<
    User, // Backend trả về User object sau khi update
    AxiosError<ApiErrorResponse>,
    UserUpdateProfile
  >({
    mutationFn: async (data) => {
      // Tạo FormData để gửi multipart/form-data (hỗ trợ file upload)
      const formData = new FormData();

      if (data.full_name !== undefined) {
        formData.append("full_name", data.full_name || "");
      }
      if (data.phone_number !== undefined) {
        formData.append("phone_number", data.phone_number || "");
      }
      if (data.email !== undefined && data.email) {
        formData.append("email", data.email);
      }
      if (data.avatar) {
        formData.append("avatar", data.avatar);
      }

      // ✅ OPTIONAL ENHANCEMENT (Deep Dive Audit): Removed manual header setting
      // API client now auto-detects FormData and sets multipart/form-data headers
      const response = await api.put<User>(API_ENDPOINTS.PROFILE.UPDATE, formData);
      return response.data;
    },
    onSuccess: (updatedUser) => {
      toast.success("Cập nhật hồ sơ thành công!");

      // ✅ GIẢI PHÁP (Tinh chỉnh DX 1):
      // Thay vì setQueryData, chúng ta invalidate ["auth", "me"].
      // Điều này đảm bảo dữ liệu (avatar, tên) ở sidebar VÀ store
      // được fetch lại 100% chính xác từ server.
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });

      // ✅ GIẢI PHÁP (Vấn đề 2):
      // Invalidate cache của trang Admin User List.
      // Lần tới khi admin vào trang /admin/users, họ sẽ thấy tên mới.
      queryClient.invalidateQueries({
        queryKey: ["admin", "users", "list"],
      });

      // Cập nhật Zustand store (vẫn giữ để UI phản ứng ngay lập tức)
      useAuthStore.getState().setUser(updatedUser);
    },
    onError: (error) => {
      let displayMessage = "Không thể cập nhật hồ sơ.";
      const errorDetail = error.response?.data?.detail;

      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (Array.isArray(errorDetail) && errorDetail.length > 0) {
        displayMessage = errorDetail[0].msg || "Lỗi xác thực";
      } else if (error.response?.data?.message) {
        displayMessage = error.response.data.message;
      }

      toast.error(displayMessage);
    },
  });

  useEffect(() => {
    if (isUserError && userError) {
      console.warn("[useAuth] Failed to fetch current user:", userError.response?.status, userError.message);
      if (userError.response?.status === 401) {
        toast.error("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
        logoutStore();
        queryClient.clear();
        router.push("/login");
      } else {
        toast.error("Không thể tải thông tin người dùng.");
      }
    }
  }, [isUserError, userError, logoutStore, queryClient, router]);

  useEffect(() => {
    if (currentUser && JSON.stringify(currentUser) !== JSON.stringify(userFromStore)) {
      useAuthStore.getState().setUser(currentUser);
    }
  }, [currentUser, userFromStore]);

  const isLoading =
    loginMutation.isPending ||
    logoutMutation.isPending ||
    registerMutation.isPending ||
    forgotPasswordMutation.isPending ||
    resetPasswordMutation.isPending ||
    changePasswordMutation.isPending ||
    updateProfileMutation.isPending ||
    verifyMfaMutation.isPending ||
    isUserLoading ||
    isUserFetching;

  return {
    user: currentUser ?? userFromStore,
    isAuthenticated: isAuthenticated && !isUserError, // ✅ SECURITY FIX: No longer check token from localStorage
    isLoading,
    login: (
      credentials: LoginRequest,
      options?: { onSuccess?: (response: LoginResponse) => void }
    ) => {
      mfaCallbackRef.current.onSuccess = options?.onSuccess;
      loginMutation.mutate(credentials);
    },
    loginAsync: loginMutation.mutateAsync,
    verifyMfa: verifyMfaMutation.mutate,
    verifyMfaError: verifyMfaMutation.error,
    resetVerifyMfa: verifyMfaMutation.reset,
    loginError: loginMutation.error,
    resetLogin: loginMutation.reset,
    logout: logoutMutation.mutate,

    registerUser: registerMutation.mutate,
    registerUserAsync: registerMutation.mutateAsync,

    forgotPassword: forgotPasswordMutation.mutate,
    resetPassword: resetPasswordMutation.mutate,
    changePassword: changePasswordMutation.mutate,
    updateProfile: updateProfileMutation.mutate,
    updateProfileAsync: updateProfileMutation.mutateAsync,
    isUpdatingProfile: updateProfileMutation.isPending,
    error:
      loginMutation.error ||
      logoutMutation.error ||
      registerMutation.error ||
      forgotPasswordMutation.error ||
      resetPasswordMutation.error ||
      changePasswordMutation.error ||
      updateProfileMutation.error ||
      verifyMfaMutation.error ||
      userError,
  };
}
