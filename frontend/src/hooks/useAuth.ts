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
} from "@/types/api.types";
import { AxiosError, AxiosRequestConfig } from "axios";
import { useEffect } from "react";
import axios from "axios"; // <<< THÊM IMPORT axios gốc để gọi API route

export function useAuth() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const {
    user: userFromStore,
    token,
    isAuthenticated,
    setAuth,
    logout: logoutStore,
  } = useAuthStore();

  const loginMutation = useMutation<
    { loginResp: LoginResponse; meResp: MeResponse },
    AxiosError<ApiErrorResponse>,
    LoginRequest
  >({
    mutationFn: async (credentials: LoginRequest) => {
      console.log("Credentials received by mutationFn:", credentials);
      const params = new URLSearchParams();
      params.append("username", credentials.username);
      params.append("password", credentials.password);

      const loginRes = await api.post<LoginResponse>(API_ENDPOINTS.AUTH.LOGIN, params, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });

      const { access_token } = loginRes.data;
      const config: AxiosRequestConfig = {
        headers: { Authorization: `Bearer ${access_token}` },
      };
      const meRes = await api.get<MeResponse>(API_ENDPOINTS.USERS.ME, config);

      return { loginResp: loginRes.data, meResp: meRes.data };
    },
    // <<< SỬA onSuccess >>>
    onSuccess: async ({ loginResp, meResp }) => {
      // Thêm async ở đây
      const { access_token, refresh_token } = loginResp;
      const user = meResp;

      try {
        // 1. Gọi API Route để set cookie httpOnly
        await axios.post("/api/auth/session", {
          accessToken: access_token,
          refreshToken: refresh_token,
        });
        console.log("[useAuth] Session cookie set successfully via API route.");

        // 2. Cập nhật state Zustand (vẫn cần thiết cho UI tức thì)
        // Không cần lưu refresh_token vào localStorage nữa
        setAuth(user, access_token /* Bỏ refresh_token ở đây nếu setAuth không cần */);
        // Nếu setAuth vẫn cần refresh_token, bạn có thể truyền undefined hoặc sửa lại setAuth
        // setAuth(user, access_token, undefined);

        toast.success("Login successful!");

        // 3. Redirect
        const redirect = new URLSearchParams(window.location.search).get("redirect");
        router.push(redirect || "/dashboard");
      } catch (error) {
        console.error("[useAuth] Failed to set session cookie via API route:", error);
        toast.error("Login succeeded but failed to set session. Please try again.");
        // Cân nhắc: Có nên logout ở đây không?
        // logoutStore(); // Gọi logout của store để reset state
      }
    },
    // <<< KẾT THÚC SỬA onSuccess >>>
    onError: (error) => {
      const displayMessage = "Login failed. Please check your credentials.";
      const errorData = error.response?.data;
      if (errorData) {
        /* ... code xử lý displayMessage ... */
      }
      toast.error(displayMessage);
    },
  });

  const logoutMutation = useMutation<void, AxiosError<ApiErrorResponse>>({
    mutationFn: async () => {
      // Gọi API logout của backend FastAPI (nếu có token)
      if (useAuthStore.getState().token) {
        await api.post(API_ENDPOINTS.AUTH.LOGOUT);
      }
    },
    onSuccess: () => {
      toast.success("Logged out successfully.");
    },
    onError: (error) => {
      console.error("Logout API call failed:", error.response?.data || error.message);
      toast.warning("Logout API call failed, proceeding with local logout.");
    },
    // <<< SỬA onSettled >>>
    onSettled: async () => {
      // Thêm async
      try {
        // 1. Gọi API Route để xóa cookie httpOnly TRƯỚC
        await axios.delete("/api/auth/session");
        console.log("[useAuth] Session cookie cleared successfully via API route.");
      } catch (error) {
        console.error("[useAuth] Failed to clear session cookie via API route:", error);
        // Vẫn tiếp tục logout phía client
      }

      // 2. Xóa state client và redirect (giữ nguyên)
      logoutStore();
      queryClient.removeQueries({ queryKey: ["auth", "me"], exact: true });
      queryClient.clear();
      router.push("/login");
    },
    // <<< KẾT THÚC SỬA onSettled >>>
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
      if (!useAuthStore.getState().token) {
        throw new Error("No token available");
      }
      const { data } = await api.get<MeResponse>(API_ENDPOINTS.USERS.ME);
      return data;
    },
    enabled: isAuthenticated && !!token,
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

      // 4. TỰ XỬ LÝ LOGOUT (Không gọi logoutMutation)
      try {
        // 4a. Gọi API Route để xóa httpOnly cookie
        await axios.delete("/api/auth/session");
        console.log("[useAuth/changePass] Session cookie cleared.");
      } catch (error) {
        console.error("[useAuth/changePass] Failed to clear session cookie.", error);
      }

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

  useEffect(() => {
    if (isUserError && userError) {
      console.error("Failed to fetch current user:", userError.response?.data || userError.message);
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
    isUserLoading ||
    isUserFetching;

  return {
    user: currentUser ?? userFromStore,
    isAuthenticated: isAuthenticated && !!token && !isUserError,
    isLoading,
    login: loginMutation.mutate,
    loginAsync: loginMutation.mutateAsync,
    logout: logoutMutation.mutate,

    registerUser: registerMutation.mutate,
    registerUserAsync: registerMutation.mutateAsync,

    forgotPassword: forgotPasswordMutation.mutate,
    resetPassword: resetPasswordMutation.mutate,
    changePassword: changePasswordMutation.mutate,
    error:
      loginMutation.error ||
      logoutMutation.error ||
      registerMutation.error ||
      forgotPasswordMutation.error ||
      resetPasswordMutation.error ||
      changePasswordMutation.error ||
      userError,
  };
}
