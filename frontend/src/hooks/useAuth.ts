// src/hooks/useAuth.ts
import { useAuthStore } from "@/lib/stores/auth.store";
import { api } from "@/lib/api/client";
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

export function useAuth(options?: UseAuthOptions) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const {
    user: userFromStore,
    isAuthenticated,
    setAuth,
    logout: logoutStore,
  } = useAuthStore();

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

      const { user, login_notification } = loginResponse;

      setAuth(user);
      triggerBannerCheck(user.password_reset_required);
      toast.success("Login successful!");

      if (login_notification) {
        const locationInfo = login_notification.location || "Unknown location";
        const deviceInfo = login_notification.device || "Unknown device";

        toast.warning(
          `Phat hien dang nhap dang ngo\nIP: ${login_notification.ip_address} - ${locationInfo}\n${deviceInfo}`,
          {
            duration: 15000,
            id: `suspicious-login-${login_notification.login_id}`,
            action: {
              label: "Xem chi tiet",
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
      const defaultPath = user.role === "officer" ? "/dashboard/officer" : "/dashboard";
      router.push(redirect || defaultPath);
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
      const { user, login_notification } = loginResponse;

      setAuth(user);
      triggerBannerCheck(user.password_reset_required);
      toast.success("Login successful!");

      if (login_notification) {
        toast.warning(
          `Phat hien dang nhap dang ngo\nIP: ${login_notification.ip_address}`,
          { duration: 15000 }
        );
      }

      const redirect = new URLSearchParams(window.location.search).get("redirect");
      const defaultPath = user.role === "officer" ? "/dashboard/officer" : "/dashboard";
      router.push(redirect || defaultPath);
    },
    // No toast here - LoginForm shows inline error via verifyMfaError
  });

  const logoutMutation = useMutation<void, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      // ========================================
      // OPTIMISTIC LOGOUT (Race Condition Fix)
      // ========================================
      // Execute cleanup BEFORE calling API to prevent race conditions
      // Order: Cancel queries → Clear cache → Redirect → API call (fire-and-forget)

      // 🛑 STEP 1: Cancel all ongoing requests immediately
      // This prevents 401 errors after logout button is clicked
      await queryClient.cancelQueries();

      // 🗑️ STEP 2: Clear all cached data
      // Prevents next user from seeing previous user's data
      queryClient.clear();

      // 🧹 STEP 3: Clear client state
      logoutStore();

      // 🚀 STEP 4: Redirect IMMEDIATELY (optimistic UI)
      // Don't wait for API response - better UX
      router.replace("/login");

      // 📡 STEP 5: Call logout API in background (fire-and-forget)
      // If this fails, it's okay - client is already cleaned up
      try {
        if (useAuthStore.getState().isAuthenticated) {
          await api.post(API_ENDPOINTS.AUTH.LOGOUT, {}, { withCredentials: true });
        }
      } catch (error) {
        // Silently fail - user is already logged out on client
        console.warn("[Logout] Background API call failed (user already logged out):", error);
      }
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
    // onSettled removed - all cleanup is done in mutationFn
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
      toast.success(`Registration successful for ${newUser.username}! Please log in.`);
      // Chuyển hướng người dùng đến trang login sau khi đăng ký thành công
      router.push("/login");
    },
    onError: (error) => {
      // Hiển thị lỗi từ backend (ví dụ: username/email đã tồn tại)
      const errorDetail = error.response?.data?.detail;
      let errorMessage = "Registration failed.";

      if (typeof errorDetail === "string") {
        errorMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        // Xử lý lỗi validation nếu backend trả về mảng
        errorMessage = errorDetail.map((e) => e.msg || "Validation error").join(", ");
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
      toast.success(data.msg || "Password reset email sent (if user exists).");
      // Có thể thêm thông báo hướng dẫn người dùng kiểm tra email
    },
    onError: (error) => {
      let displayMessage = "Failed to send password reset email."; // Default message
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
      toast.success(`Password for ${user.username} has been reset successfully! Please log in.`);
      router.push("/login"); // Chuyển về trang login sau khi reset thành công
    },
    onError: (error) => {
      let displayMessage = "Failed to reset password.";
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
        displayMessage = "Invalid or expired password reset token.";
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
      toast.success("Password changed successfully! Logging out...");

      // 4b. Dọn dẹp state client (Zustand)
      logoutStore();
      // 4c. Dọn dẹp cache (React Query)
      queryClient.clear();
      // 4d. Chuyển hướng
      router.push("/login");
    },
    onError: (error) => {
      // 5. Xử lý lỗi (giữ nguyên)
      let displayMessage = "Failed to change password.";
      const errorDetail = error.response?.data?.detail;
      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
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
      toast.success("Profile updated successfully!");

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
      let displayMessage = "Failed to update profile.";
      const errorDetail = error.response?.data?.detail;

      if (typeof errorDetail === "string") {
        displayMessage = errorDetail;
      } else if (Array.isArray(errorDetail)) {
        displayMessage = errorDetail[0].msg || "Validation error";
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
        toast.error("Your session has expired. Please log in again.");
        logoutStore();
        queryClient.clear();
        router.push("/login");
      } else {
        toast.error("Could not fetch user data.");
      }
    }
  }, [isUserError, userError, logoutStore, queryClient, router]);

  useEffect(() => {
    if (currentUser && !userFromStore) {
      if (JSON.stringify(currentUser) !== JSON.stringify(userFromStore)) {
        // <<< SỬA LỖI 2: setUser nhận User từ api.types >>>
        useAuthStore.getState().setUser(currentUser); // TypeScript sẽ kiểm tra kiểu User ở đây
      }
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
